"""Rank-buffered portfolio recommendations with explicit constraints."""

from __future__ import annotations

import math
from dataclasses import asdict

from finance_analysis.quant.config import PortfolioConfig
from finance_analysis.quant.exceptions import PortfolioConstraintError


class PortfolioBuilder:
    def __init__(self, config: PortfolioConfig | None = None):
        self.config = config or PortfolioConfig()

    def build(
        self,
        signals: list[dict],
        max_equity_exposure: float,
        current_weights: dict[str, float] | None = None,
    ) -> dict:
        current_weights = current_weights or {}
        missing_metadata = {
            item.get("code", "<unknown>"): [
                key for key in ("has_sufficient_data", "liquidity") if item.get(key) is None
            ]
            for item in signals
            if any(item.get(key) is None for key in ("has_sufficient_data", "liquidity"))
        }
        if missing_metadata:
            detail = ", ".join(f"{code}={fields}" for code, fields in sorted(missing_metadata.items()))
            raise PortfolioConstraintError(f"Portfolio metadata is missing: {detail}")

        ordered = sorted(signals, key=lambda item: item["final_score"], reverse=True)
        ranked = [{**item, "rank": rank} for rank, item in enumerate(ordered, 1)]
        eligible = [
            item
            for item in ranked
            if not item.get("vetoed")
            and item["has_sufficient_data"]
            and float(item["liquidity"]) >= self.config.minimum_liquidity
        ]
        allocation_candidates = [item for item in eligible if item.get("signal") == "buy"]
        display_candidates = [item for item in eligible if item.get("signal") in {"buy", "watch", "hold"}]
        buys = allocation_candidates[: self.config.buy_top_k]
        watch_codes = {item["code"] for item in display_candidates[: self.config.watch_top_k]}
        selected_codes = {item["code"] for item in buys}
        for item in eligible:
            if (
                current_weights.get(item["code"], 0) > 0
                and item["rank"] <= self.config.hold_rank_threshold
                and item.get("signal") in {"buy", "watch", "hold"}
            ):
                selected_codes.add(item["code"])

        raw_weights = self._weights(
            [item for item in eligible if item["code"] in selected_codes],
            max_equity_exposure,
        )
        sector_totals: dict[str, float] = {}
        new_exposure = 0.0
        turnover = 0.0
        rows = []
        insufficient_data = []
        insufficient_liquidity = []
        for item in ranked:
            code = item["code"]
            sector = item.get("sector_key")
            current = float(current_weights.get(code, 0))
            target = raw_weights.get(code, 0)
            constraints = []

            allowed_sector = (
                max(0, self.config.sector_max_weight - sector_totals.get(sector, 0))
                if sector
                else max_equity_exposure
            )
            target = min(
                target,
                allowed_sector,
                self.config.single_stock_max_weight,
                max_equity_exposure,
            )
            if item.get("vetoed"):
                target = 0
                constraints.append("vetoed")
            if not item["has_sufficient_data"]:
                target = 0
                constraints.append("insufficient_data")
                insufficient_data.append(code)
            if float(item["liquidity"]) < self.config.minimum_liquidity:
                target = 0
                constraints.append("insufficient_liquidity")
                insufficient_liquidity.append(code)

            # Preserve an existing eligible position inside the sell buffer. This
            # prevents rank 16-20 holdings from becoming zero-weight "watch" rows.
            if (
                current > 0
                and not constraints
                and code not in selected_codes
                and item["rank"] <= self.config.sell_rank_threshold
                and item.get("signal") != "reduce"
            ):
                target = current
                constraints.append("sell_rank_buffer")

            increase = max(0, target - current)
            if new_exposure + increase > self.config.maximum_daily_new_exposure:
                target = current + max(0, self.config.maximum_daily_new_exposure - new_exposure)
                constraints.append("daily_new_exposure")
            change = target - current
            if turnover + abs(change) > self.config.maximum_daily_turnover:
                remaining_turnover = max(0, self.config.maximum_daily_turnover - turnover)
                target = current + math.copysign(remaining_turnover, change)
                change = target - current
                constraints.append("daily_turnover")

            new_exposure += max(0, change)
            turnover += abs(change)
            if sector:
                sector_totals[sector] = sector_totals.get(sector, 0) + target
            if item.get("vetoed"):
                action = "blocked"
            elif target > current and current == 0:
                action = "buy"
            elif target > current:
                action = "increase"
            elif target == current and target > 0:
                action = "hold"
            elif target < current and target > 0:
                action = "reduce"
            elif current > 0 and target == 0:
                action = "sell"
            elif code in watch_codes:
                action = "watch"
            else:
                continue
            rows.append(
                {
                    **item,
                    "action": action,
                    "current_weight": current,
                    "target_weight": target,
                    "weight_change": target - current,
                    "constraints": constraints,
                }
            )

        warnings = []
        if not buys:
            warnings.append("当前没有满足建仓阈值的 buy 信号，组合未新增仓位")
        if insufficient_data:
            warnings.append(f"Insufficient daily history: {sorted(set(insufficient_data))}")
        if insufficient_liquidity:
            warnings.append(f"Insufficient liquidity: {sorted(set(insufficient_liquidity))}")
        return {
            "items": rows,
            "target_equity_exposure": sum(item["target_weight"] for item in rows),
            "sector_exposure": sector_totals,
            "warnings": warnings,
            "config": asdict(self.config),
        }

    def _weights(self, selected: list[dict], exposure: float) -> dict[str, float]:
        if not selected:
            return {}
        cap = min(exposure, self.config.single_stock_max_weight * len(selected))
        if self.config.weighting == "equal_weight":
            return {item["code"]: cap / len(selected) for item in selected}
        if self.config.weighting == "score_weight":
            total = sum(max(0, item["final_score"]) for item in selected)
            return {
                item["code"]: (cap * max(0, item["final_score"]) / total if total else cap / len(selected))
                for item in selected
            }
        raise ValueError(f"Unknown weighting: {self.config.weighting}")
