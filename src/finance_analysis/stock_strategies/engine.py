"""One deterministic daily transition: prior plan -> open fills -> close decisions."""

from copy import deepcopy
from math import isfinite

import numpy as np

from finance_analysis.stock_strategies.features import DataNotReady, finite
from finance_analysis.stock_strategies.registry import INITIAL_CAPITAL
from finance_analysis.stock_strategies.signals import decide


def native_scalars(value):
    """Keep NumPy reprs out of SQL parameters and JSON state/payloads."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: native_scalars(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [native_scalars(item) for item in value]
    return value


def initial_state():
    return dict(
        cash=INITIAL_CAPITAL,
        nav=INITIAL_CAPITAL,
        nav_peak=INITIAL_CAPITAL,
        cycle_peak=INITIAL_CAPITAL,
        max_drawdown=0.0,
        positions={},
        plan=None,
        pause_remaining=0,
        stopped=False,
        sessions=0,
        macro_bad=0,
        breadth_bad=0,
        closed_rounds=0,
        wins=0,
        turnover=0.0,
        turnover_ratio=0.0,
        benchmark_value=1.0,
        benchmark_mark_date=None,
    )


def executable(data, code, side):
    f = data.features.get(code, {})
    if not finite(f.get("open")) or f["open"] <= 0:
        return False
    if data.market == "CN":
        from finance_analysis.market_review.price_limits import resolve_price_limit_rule

        instrument = data.instruments.get(code, {})
        limit = resolve_price_limit_rule(
            code=code,
            name=instrument.get("name", ""),
            pre_close=f.get("previous_close"),
            today=data.day,
            security_type=instrument.get("type", "STOCK").lower(),
        ).limit_ratio
        if limit is not None:
            previous = f.get("previous_close")
            if not finite(previous) or previous <= 0:
                return False
            gap = f["open"] / previous - 1
            if (side == "BUY" and gap >= limit - 0.001) or (side == "SELL" and gap <= -limit + 0.001):
                return False
    return True


def rebase(position, data, code):
    anchor = data.prices.get(code, {}).get(position["mark_date"])
    if not finite(anchor) or anchor <= 0:
        raise DataNotReady(f"缺少{code}持仓估值锚点{position['mark_date']}，无法核对复权尺度")
    scale = anchor / position["mark"]
    if abs(scale - 1) < 1e-9:
        return None
    old = position["quantity"]
    position["quantity"] /= scale
    for key in ("mark", "entry_price", "peak", "stop"):
        if position.get(key) is not None:
            position[key] *= scale
    return dict(
        code=code,
        scale=scale,
        quantity_before=old,
        quantity_after=position["quantity"],
        reason="前复权尺度桥接，保持此前持仓价值与成本不变",
    )


def advance(spec, previous, data, start_date):
    state = deepcopy(previous)
    positions = state["positions"]
    fills, adjustments, blocked, warnings = [], [], [], []
    old_nav = state["nav"]
    for code, pos in positions.items():
        change = rebase(pos, data, code)
        if change:
            adjustments.append(change)
    plan = state["plan"]
    if plan and plan["execution_date"] != data.day.isoformat():
        raise ValueError("待执行计划日期与下一结算交易日不一致")
    if not plan and state["sessions"]:
        raise ValueError("连续账本缺少上一交易日计划")
    # Risk pause counts exchange opens, including the first attempted liquidation.
    paused = state["pause_remaining"] > 0
    if paused:
        state["pause_remaining"] -= 1
    if state["stopped"] and not paused and not positions and spec.risk_engine in {"20261021", "20261023"}:
        state["stopped"] = False
        state["cycle_peak"] = state["cash"]
    traded = set()
    if plan:
        for code, pos in list(positions.items()):
            reasons = list(dict.fromkeys([*pos.get("pending_exit", []), *plan["exits"].get(code, [])]))
            if not reasons:
                continue
            if not executable(data, code, "SELL"):
                pos["pending_exit"] = reasons
                blocked.append(dict(code=code, action="SELL", reason="卖出开盘不可交易，保留待卖出状态"))
                continue
            price, quantity = data.features[code]["open"], pos["quantity"]
            pnl = quantity * (price - pos["entry_price"])
            state["cash"] += quantity * price
            state["turnover"] += quantity * price
            state["closed_rounds"] += 1
            state["wins"] += int(pnl > 0)
            fills.append(
                dict(
                    code=code,
                    name=pos["name"],
                    action="SELL",
                    quantity=quantity,
                    price=price,
                    amount=quantity * price,
                    pnl=pnl,
                    reasons=reasons,
                    signal_date=plan["signal_date"],
                )
            )
            del positions[code]
            traded.add(code)
        opening = state["cash"] + sum(
            p["quantity"]
            * (
                data.features[c]["open"]
                if finite(data.features.get(c, {}).get("open")) and data.features[c]["open"] > 0
                else p["mark"]
            )
            for c, p in positions.items()
        )
        can_buy = not paused
        if state["stopped"]:
            # October 23 research resumes only when already flat at the open.
            # A delayed liquidation after cooldown must wait until the next open.
            can_buy = can_buy and not positions and spec.risk_engine != "20261023"
        if can_buy:
            for candidate in plan["candidates"]:
                if len(positions) >= spec.slots:
                    break
                code = candidate["code"]
                if code in positions or code in traded or plan["exits"].get(code):
                    continue
                if not executable(data, code, "BUY"):
                    blocked.append(dict(code=code, action="BUY", reason="买入开盘不可交易；本次候选不成交"))
                    continue
                price = data.features[code]["open"]
                # Signal ATR lives in yesterday's price scale; anchor at yesterday's close.
                signal_close = data.prices.get(code, {}).get(plan["signal_date"])
                if not finite(signal_close) or signal_close <= 0:
                    raise DataNotReady(f"缺少{code}信号日复权锚点")
                scale = signal_close / candidate["signal_close"]
                atr = candidate["atr"] * scale
                budget = min(state["cash"], opening / spec.slots)
                if budget <= 0.000001:
                    continue
                if state["stopped"]:
                    state["cycle_peak"] = opening
                    state["stopped"] = False
                quantity = budget / price
                positions[code] = dict(
                    quantity=quantity,
                    entry_price=price,
                    name=candidate["name"],
                    mark=price,
                    mark_date=data.day.isoformat(),
                    peak=price,
                    stop=price - spec.atr * atr if spec.atr else None,
                    pending_exit=[],
                )
                state["cash"] -= budget
                state["turnover"] += budget
                traded.add(code)
                fills.append(
                    dict(
                        code=code,
                        name=candidate["name"],
                        action="BUY",
                        quantity=quantity,
                        price=price,
                        amount=budget,
                        pnl=None,
                        reasons=["上一交易日收盘候选入场"],
                        signal_date=plan["signal_date"],
                    )
                )
    # A suspended/missing close is valued at its last observed mark and explicitly disclosed.
    stale = []
    for code, pos in positions.items():
        f = data.features.get(code, {})
        if f.get("valid"):
            pos["mark"], pos["mark_date"] = f["close"], data.day.isoformat()
        else:
            stale.append(code)
    nav = state["cash"] + sum(p["quantity"] * p["mark"] for p in positions.values())
    if not isfinite(nav) or nav <= 0 or state["cash"] < -0.000001:
        raise ValueError("模拟账户净值或现金守恒校验失败")
    state["nav"] = nav
    state["turnover_ratio"] += sum(f["amount"] for f in fills) / nav
    decision = decide(spec, state, data)
    # Compare with the existing stop before incorporating this close's peak/ATR.
    for code, pos in positions.items():
        f = data.features.get(code, {})
        reasons = decision["exits"].setdefault(code, [])
        if f.get("valid") and pos["stop"] is not None and f["close"] < pos["stop"]:
            reasons.append("收盘跌破此前ATR跟踪线")
        if f.get("valid"):
            pos["peak"] = max(pos["peak"], f["close"])
            if spec.atr and finite(f.get("atr")):
                pos["stop"] = max(pos["stop"], pos["peak"] - spec.atr * f["atr"])
    if not state["stopped"]:
        state["cycle_peak"] = max(state["cycle_peak"], nav)
        threshold = state["cycle_peak"] * (1 - spec.account_dd)
        triggered = nav <= threshold if spec.risk_engine == "20261020" else nav < threshold
        if spec.account_dd and positions and triggered:
            state["stopped"], state["pause_remaining"] = True, spec.cooldown
            for code in positions:
                decision["exits"].setdefault(code, []).append("账户回撤触发清仓与暂停")
    state["macro_bad"], state["breadth_bad"] = decision["macro_bad"], decision["breadth_bad"]
    for item in decision["candidates"]:
        item["signal_close"] = data.features[item["code"]]["close"]
    exits = {
        c: list(dict.fromkeys([*positions[c].get("pending_exit", []), *decision["exits"].get(c, [])]))
        for c in positions
    }
    candidates = [r for r in decision["candidates"] if not decision["exits"].get(r["code"])]
    state["plan"] = dict(
        signal_date=data.day.isoformat(),
        execution_date=data.next_day.isoformat(),
        candidates=candidates,
        exits=exits,
        status="PAUSED" if state["pause_remaining"] or (state["stopped"] and positions) else "READY",
    )
    state["nav_peak"] = max(state["nav_peak"], nav)
    drawdown = nav / state["nav_peak"] - 1
    state["max_drawdown"] = min(state["max_drawdown"], drawdown)
    state["sessions"] += 1
    benchmark = data.features.get(data.benchmark, {})
    if not benchmark.get("valid"):
        raise DataNotReady("等待当日基准有效收盘")
    if state["benchmark_mark_date"]:
        anchor = data.prices.get(data.benchmark, {}).get(state["benchmark_mark_date"])
        if not finite(anchor) or anchor <= 0:
            raise DataNotReady("缺少基准复权估值锚点")
        state["benchmark_value"] *= benchmark["close"] / anchor
    state["benchmark_mark_date"] = data.day.isoformat()
    years = ((data.day - start_date).days + 1) / 365.25
    cagr = float((nav / INITIAL_CAPITAL) ** (1 / years) - 1) if state["sessions"] >= 20 else None
    if cagr is not None and not isfinite(cagr):
        cagr = None
    if stale:
        warnings.append("以下持仓缺少有效收盘，暂用最后估值：" + ", ".join(stale))
    payload = dict(
        cash=state["cash"],
        positions=positions,
        fills=fills,
        adjustments=adjustments,
        blocked=blocked,
        plan=state["plan"],
        warnings=warnings,
        stale_codes=stale,
        sessions=state["sessions"],
        closed_rounds=state["closed_rounds"],
        win_rate=state["wins"] / state["closed_rounds"] if state["closed_rounds"] else None,
        annual_turnover=state["turnover_ratio"] / years,
        pause_remaining=state["pause_remaining"],
        breadth=decision["breadth"],
        breadth_denominator=decision["breadth_denominator"],
        provenance=data.provenance,
        next_is_historical=False,
    )
    snapshot = dict(
        nav=nav,
        daily_return=nav / old_nav - 1,
        total_return=nav / INITIAL_CAPITAL - 1,
        cagr=cagr,
        drawdown=drawdown,
        max_drawdown=state["max_drawdown"],
        exposure=(nav - state["cash"]) / nav,
        benchmark_return=state["benchmark_value"] - 1,
        payload=deepcopy(payload),
    )
    return native_scalars(state), native_scalars(snapshot)
