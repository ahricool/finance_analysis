"""Build a model target portfolio from fused daily signals."""

from __future__ import annotations

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
        selected = eligible[: self.config.buy_top_k]
        target_weights = self._weights(selected, max_equity_exposure)
        rows = [
            {
                **item,
                "target_weight": target_weights[item["code"]],
                "constraints": ["single_stock_max_weight", "max_equity_exposure"],
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
