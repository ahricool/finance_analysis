"""Daily prediction portfolio research with T+1-open execution."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from finance_analysis.quant.models.metrics import portfolio_metrics


@dataclass(frozen=True)
class BacktestCostConfig:
    commission_bps: float = 2.0
    slippage_bps: float = 3.0
    minimum_commission: float = 0.0
    sell_tax_bps: float = 0.0


def run_topk_backtest(predictions: pd.DataFrame, bars: pd.DataFrame, benchmark: pd.DataFrame, top_k: int = 5, score_weighted: bool = False,
                      buffer_rank: int = 15, costs: BacktestCostConfig = BacktestCostConfig()) -> dict:
    """Signals at T close are filled at the next available open, never T close."""
    prices=bars.sort_values(["code","date"]).copy(); prices["next_open"]=prices.groupby("code").open.shift(-1); prices["next_close"]=prices.groupby("code").close.shift(-1)
    merged=predictions.merge(prices[["code","date","next_open","next_close"]],on=["code","date"],how="left"); merged["gross_return"]=merged.next_close/merged.next_open-1
    previous=set(); daily=[]; turnovers=[]
    for day, group in merged.groupby("date",sort=True):
        ranked=group.sort_values("score",ascending=False); keep={code for code in previous if code in set(ranked.head(buffer_rank).code)}; selected=list(keep)
        selected += [code for code in ranked.code if code not in keep][:max(0,top_k-len(selected))]; chosen=ranked[ranked.code.isin(selected)].copy()
        if chosen.empty: continue
        if score_weighted:
            positive=chosen.score.clip(lower=0); chosen["weight"]=positive/positive.sum() if positive.sum() else 1/len(chosen)
        else: chosen["weight"]=1/len(chosen)
        turnover=len(previous.symmetric_difference(set(selected)))/max(top_k,1); fee=turnover*(costs.commission_bps+costs.slippage_bps+costs.sell_tax_bps)/10000
        daily.append((day,float((chosen.weight*chosen.gross_return).sum()-fee))); turnovers.append((day,turnover)); previous=set(selected)
    returns=pd.Series(dict(daily),dtype=float).sort_index(); turnover_series=pd.Series(dict(turnovers),dtype=float).sort_index()
    bench=benchmark.sort_values("date").set_index("date"); benchmark_returns=bench.close.pct_change().reindex(returns.index)
    return {"metrics":portfolio_metrics(returns,turnover_series),"daily_returns":returns.to_dict(),"benchmark_returns":benchmark_returns.to_dict(),
            "excess_return":float((returns-benchmark_returns).dropna().sum()),"warnings":["results depend on fixed-index market-data coverage"]}
