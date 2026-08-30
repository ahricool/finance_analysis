"""Deterministic comparison narrative from the fixed strategy metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _row(results: Sequence[Mapping[str, Any]], strategy_id: str) -> Mapping[str, Any] | None:
    return next((item for item in results if item.get("strategy_id") == strategy_id), None)


def _pct(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):.2%}"


def _num(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):.3f}"


def _better(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None, field: str, higher: bool = True) -> str:
    if left is None or right is None:
        return "数据不足，无法比较。"
    lv, rv = left.get(field), right.get(field)
    if lv is None or rv is None:
        return "数据不足，无法比较。"
    percent_fields = {
        "cagr",
        "max_drawdown",
        "win_rate",
        "turnover",
        "mae",
        "mfe",
        "avg_trade_return",
        "cash_ratio",
        "total_return",
    }
    fmt = _pct if field in percent_fields else _num
    left_wins = float(lv) > float(rv) if higher else float(lv) < float(rv)
    winner = left if left_wins else right
    return (
        f"{left['strategy_id']} {field}={fmt(lv)}，{right['strategy_id']} 为 {fmt(rv)}。"
        f"按该指标更优的是 {winner['strategy_id']}。"
    )


def build_analysis(
    market: str,
    comparison: Sequence[Mapping[str, Any]],
    entry1_split: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    a = _row(comparison, "A_baseline")
    b = _row(comparison, "B_entry1_mom10")
    c = _row(comparison, "C_entry1_mom20")
    d = _row(comparison, "D_top3_mom10")
    e = _row(comparison, "E_top3_mom20")
    f = _row(comparison, "F_top3_absolute")
    g = _row(comparison, "G_f_stop")
    h = _row(comparison, "H_f_riskoff")
    i = _row(comparison, "I_hysteresis")
    overnight = (entry1_split or {}).get("t_close_to_next_open") or {}
    intraday = (entry1_split or {}).get("t1_open_to_t1_close") or {}

    ranked = [row for row in comparison if row.get("sharpe") not in (None, "")]
    ranked.sort(key=lambda row: (float(row["sharpe"]), float(row.get("cagr") or 0)), reverse=True)
    recommended = ranked[0] if ranked else (comparison[0] if comparison else None)

    overnight_mean = overnight.get("mean")
    overnight_note = ""
    if overnight_mean is not None and a is not None:
        if float(overnight_mean) > 0:
            overnight_note = (
                f"Entry#1 在 T 收盘到 T+1 开盘的隔夜收益均值为 {_pct(overnight_mean)}，"
                "而策略只能在次日开盘买入，因此隔夜缺口会被吃掉，这是 Baseline 年化偏弱的重要来源。"
            )
        else:
            overnight_note = (
                f"Entry#1 隔夜收益均值为 {_pct(overnight_mean)}，开盘执行并非主要拖累；"
                "更可能来自高频换仓、赢家回吐或动量衰减。"
            )

    lines = [
        f"# {market} ETF Momentum Rotation 策略对比",
        "",
        "## Baseline 年化低的主要原因",
        overnight_note or "缺少 Entry#1 隔夜拆分。",
        (
            f"Baseline CAGR={_pct(a.get('cagr') if a else None)}，"
            f"换手={_pct(a.get('turnover') if a else None)}，"
            f"平均持仓天数={_num(a.get('avg_holding_days') if a else None)}，"
            f"年化交易次数={_num(a.get('trades_per_year') if a else None)}。"
            "若换手高、持仓短，说明 Entry Rank 前二过滤仍过于敏感，容易在噪声排名上反复换仓。"
        ),
        f"Entry#1 次日开盘到收盘均值 {_pct(intraday.get('mean'))}，可用于判断日内是否还能兑现动量。",
        "",
        "## Top1 还是 Top3",
        _compare_group("Top1 代表", [a, b, c], "CAGR/Sharpe", "cagr"),
        _compare_group("Top3 代表", [d, e, f], "CAGR/Sharpe", "cagr"),
        _pick_better_by_sharpe("Top1 最佳", [a, b, c], "Top3 最佳", [d, e, f]),
        "",
        "## Momentum 10 vs 20 退出",
        f"单票：{_better(b, c, 'cagr')} Sharpe：{_better(b, c, 'sharpe')} 回撤：{_better(b, c, 'max_drawdown')} 换手：{_better(b, c, 'turnover', higher=False)}",
        f"Top3：{_better(d, e, 'cagr')} Sharpe：{_better(d, e, 'sharpe')} 回撤：{_better(d, e, 'max_drawdown')} 换手：{_better(d, e, 'turnover', higher=False)}",
        "若 Momentum 10 换手明显更高而收益没有更好，则 20 作为退出阈值更合理；反之说明动量衰减很快，应更早离场。",
        "",
        "## Absolute Filter 是否有效",
        f"{_better(f, e, 'cagr')} Sharpe {_better(f, e, 'sharpe')} 回撤 {_better(f, e, 'max_drawdown')} 胜率 {_better(f, e, 'win_rate')}",
        "若 F 相对 E 提高胜率或降低回撤，说明 ret_5d>0 且站上 MA20 的过滤有效；若收益下降很多，则过滤过严、错过主升。",
        "",
        "## Risk-Off 是否改善回撤",
        f"{_better(h, f, 'max_drawdown')} CAGR {_better(h, f, 'cagr')} 现金比例 {_better(h, f, 'cash_ratio')}",
        "若 H 回撤更小且现金比例更高，说明 30% 广度过滤起到避险作用；若回撤几乎不变，则该样本里系统性下跌不够集中。",
        "",
        "## Stop 是否改善 downside",
        f"回撤 {_better(g, f, 'max_drawdown')} MAE {_better(g, f, 'mae')} CAGR {_better(g, f, 'cagr')}",
        "止损只上移、以 T+1 开盘成交价为锚。若 MAE/回撤改善但 CAGR 明显变差，说明止损在正常波动里被扫出。",
        "",
        "## Hysteresis 是否减少无效换仓",
        f"换手 {_better(i, d, 'turnover', higher=False)} 相对 D；相对 E：{_better(i, e, 'turnover', higher=False)} 持仓天数 {_better(i, e, 'avg_holding_days')}",
        "若 I 换手下降而 Sharpe 不差，说明 16-20 观察带减少了噪声退出。",
        "",
        "## 推荐继续使用",
    ]
    if recommended:
        lines.append(
            f"按 Sharpe 优先（同分看 CAGR），推荐 **{recommended['strategy_id']}** "
            f"({recommended.get('strategy_name')})：CAGR={_pct(recommended.get('cagr'))}，"
            f"Sharpe={_num(recommended.get('sharpe'))}，MaxDD={_pct(recommended.get('max_drawdown'))}，"
            f"换手={_pct(recommended.get('turnover'))}。"
        )
        lines.append("以上均为固定规则对比，没有做参数搜索。")
    return "\n".join(lines) + "\n"


def _compare_group(label: str, rows: Sequence[Mapping[str, Any] | None], _unused: str, field: str) -> str:
    present = [row for row in rows if row is not None]
    if not present:
        return f"{label}：无结果。"
    best = max(present, key=lambda row: float(row.get(field) or float("-inf")))
    parts = ", ".join(f"{row['strategy_id']} {field}={_pct(row.get(field))}" for row in present)
    return f"{label}：{parts}。最佳 {best['strategy_id']}。"


def _pick_better_by_sharpe(left_label: str, left: Sequence[Mapping[str, Any] | None], right_label: str, right: Sequence[Mapping[str, Any] | None]) -> str:
    def best(rows: Sequence[Mapping[str, Any] | None]) -> Mapping[str, Any] | None:
        present = [row for row in rows if row is not None and row.get("sharpe") not in (None, "")]
        return max(present, key=lambda row: float(row["sharpe"])) if present else None

    left_best, right_best = best(left), best(right)
    if left_best is None or right_best is None:
        return "Top1/Top3 无法完整比较。"
    winner = left_best if float(left_best["sharpe"]) >= float(right_best["sharpe"]) else right_best
    family = left_label if winner is left_best else right_label
    return (
        f"{left_label} {left_best['strategy_id']} Sharpe={_num(left_best.get('sharpe'))}；"
        f"{right_label} {right_best['strategy_id']} Sharpe={_num(right_best.get('sharpe'))}。"
        f"当前样本更看好{family}（{winner['strategy_id']}）。"
    )


def write_analysis(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


__all__ = ["build_analysis", "write_analysis"]
