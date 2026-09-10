"""Build a model target portfolio from fused daily signals."""

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
    ) -> dict:
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
            if item["has_sufficient_data"]
            and float(item["liquidity"]) >= self.config.minimum_liquidity
            and item.get("signal") == "buy"
        ]
        selected = eligible[: self._selection_count(len(eligible), max_equity_exposure)]
        target_weights = self._weights(selected, max_equity_exposure)
        rows = [
            {
                **item,
                "target_weight": target_weights[item["code"]],
                "constraints": {
                    "limits": {
                        "single_stock_max_weight": self.config.single_stock_max_weight,
                        "max_equity_exposure": max_equity_exposure,
                        "buy_top_k": self.config.buy_top_k,
                        "selected_count": len(selected),
                    }
                },
            }
            for item in selected
        ]

        insufficient_data = [item["code"] for item in ranked if not item["has_sufficient_data"]]
        insufficient_liquidity = [
            item["code"]
            for item in ranked
            if item["has_sufficient_data"] and float(item["liquidity"]) < self.config.minimum_liquidity
        ]
        warnings = []
        if not selected:
            warnings.append("当前没有满足入选阈值的 buy 信号，目标组合为空")
        achievable = self.config.single_stock_max_weight * len(selected)
        if selected and achievable + 1e-12 < max_equity_exposure:
            warnings.append(
                "max_equity_exposure "
                f"{max_equity_exposure:.0%} exceeds {len(selected)} × "
                f"{self.config.single_stock_max_weight:.0%} single-stock cap; "
                f"target exposure is capped at {achievable:.0%}"
            )
        if insufficient_data:
            warnings.append(f"Insufficient daily history: {sorted(set(insufficient_data))}")
        if insufficient_liquidity:
            warnings.append(f"Insufficient liquidity: {sorted(set(insufficient_liquidity))}")
        return {
            "items": rows,
            "target_equity_exposure": sum(item["target_weight"] for item in rows),
            "warnings": warnings,
            "config": asdict(self.config),
        }

    def _selection_count(self, eligible_count: int, max_equity_exposure: float) -> int:
        name_cap = self.config.single_stock_max_weight
        if name_cap <= 0:
            raise ValueError("single_stock_max_weight must be positive")
        required = math.ceil(max(0.0, float(max_equity_exposure)) / name_cap - 1e-12)
        return min(eligible_count, max(self.config.buy_top_k, required))

    def _weights(self, selected: list[dict], exposure: float) -> dict[str, float]:
        if not selected:
            return {}
        name_cap = self.config.single_stock_max_weight
        total_cap = min(max(0.0, float(exposure)), name_cap * len(selected))
        weight = total_cap / len(selected)
        return {item["code"]: min(weight, name_cap) for item in selected}
