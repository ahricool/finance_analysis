"""Sector ranking that preserves raw scores under market gating."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


class SectorRegimeService:
    def rank(self, sectors: dict[str, tuple[str, pd.DataFrame, dict[str, pd.DataFrame]]], market: pd.DataFrame, market_regime: str) -> list[dict]:
        market = market.sort_values("date"); market_ret5 = market.close.iloc[-1] / market.close.iloc[-6] - 1; market_ret20 = market.close.iloc[-1] / market.close.iloc[-21] - 1
        rows = []
        for key, (benchmark_code, benchmark, members) in sectors.items():
            frame = benchmark.sort_values("date"); close = frame.close.astype(float)
            if len(frame) < 61: continue
            ret5, ret20 = close.iloc[-1] / close.iloc[-6] - 1, close.iloc[-1] / close.iloc[-21] - 1
            breadth = [bars.sort_values("date").close.iloc[-1] > bars.sort_values("date").close.tail(20).mean() for bars in members.values() if len(bars) >= 20]
            features = {"sector_ret_5d": ret5, "sector_ret_20d": ret20, "sector_relative_market_5d": ret5-market_ret5,
                        "sector_relative_market_20d": ret20-market_ret20, "sector_ma20_state": float(close.iloc[-1]/close.tail(20).mean()-1),
                        "sector_ma60_state": float(close.iloc[-1]/close.tail(60).mean()-1), "sector_realized_vol": float(close.pct_change().tail(20).std()*math.sqrt(252)),
                        "sector_breadth": float(np.mean(breadth)) if breadth else None}
            available = [np.clip((features["sector_relative_market_20d"]+.1)/.2,0,1), np.clip((features["sector_ma20_state"]+.1)/.2,0,1)]
            if features["sector_breadth"] is not None: available.append(features["sector_breadth"])
            score = float(np.mean(available)); state = "strong" if score >= .65 else "weak" if score <= .35 else "neutral"
            if market_regime == "risk_off": state = "blocked"
            rows.append({"sector_key": key, "benchmark_code": benchmark_code, "sector_score": score, "state": state, "features": features})
        rows.sort(key=lambda item: item["sector_score"], reverse=True)
        for rank, row in enumerate(rows, 1): row["rank"] = rank
        return rows
