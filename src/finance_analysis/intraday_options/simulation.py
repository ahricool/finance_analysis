"""Underlying-only paper execution. Pure transitions, immutable entry evidence."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds

VERSION = "underlying_sim_v1"


@dataclass(frozen=True)
class ExecutionConfig:
    quote_age_seconds: int = 30
    entry_max_atr: float = 1.0
    no_progress_minutes: int = 20
    minimum_progress_r: float = 0.25
    protect_after_r: float = 1.0
    giveback_r: float = 0.5
    stop_before_close_hours: int = 2
    workers: int = 4


CONFIG = ExecutionConfig()


def dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def quote_value(quote, now):
    if not quote or quote.timestamp_kind == "received" or not quote.event_time or not quote.received_at:
        return None
    if quote.trading_date != market_trading_date(now, "US"):
        return None
    if any(
        not 0 <= (now - t).total_seconds() <= CONFIG.quote_age_seconds for t in (quote.event_time, quote.received_at)
    ):
        return None
    price = float(quote.last_price or 0)
    return price if math.isfinite(price) and price > 0 else None


def plan(branch, result, price, now):
    side = 1 if branch["direction"] == "bullish" else -1
    trigger, scale = branch["trigger"], branch["atr"]
    floor = 0.1 if branch["kind"] == "trend_recovery" else 0.2
    interval = sorted([trigger + side * floor * scale, trigger + side * CONFIG.entry_max_atr * scale])
    # Confirmed pivots are raw intraday prices, the same basis as execution quotes.
    candidates = [
        p["price"]
        for p in result.get("execution_pivots", [])
        if p["kind"] == ("high" if side == 1 else "low")
        and dt(p["confirmed_at"]) <= now
        and price is not None
        and (p["price"] - price) * side > 0
    ]
    target = min(candidates, key=lambda p: (p - price) * side) if candidates else branch.get("measurement_target")
    source = "已确认结构位" if candidates else "箱体高度测量估计" if target else "未知"
    reason = "可以模拟进场"
    if branch["status"] != "confirmed":
        reason = "等待形态确认或独立新机会"
    elif now >= dt(branch["expires_at"]):
        reason = "机会已过期"
    elif price is None:
        reason = "报价缺失、过期或时间异常"
    elif (price - branch["invalidation"]) * side <= 0:
        reason = "最新价格已越过失效位"
    elif not interval[0] <= price <= interval[1]:
        reason = "最新价格不在入场区间（等待恢复或已延伸）"
    elif target is not None and (target - price) * side <= 0:
        reason = "目标已越过，放弃本次进场"
    reward = (target - price) * side if target is not None and price is not None else None
    risk = (price - branch["invalidation"]) * side if price is not None else None
    return {
        **deepcopy(branch),
        "process_id": branch.get("process_id", branch["structure_id"]),
        "entry_low": interval[0],
        "entry_high": interval[1],
        "target": target,
        "target_source": source,
        "remaining_space": reward,
        "reward_risk": reward / risk if reward is not None and risk and risk > 0 else None,
        "minute_as_of": result.get("as_of"),
        "rule_version": VERSION,
        "age_seconds": (now - dt(branch["confirmed_at"])).total_seconds() if branch["confirmed_at"] else None,
        "executable": reason == "可以模拟进场",
        "execution_reason": reason,
    }


def transition(previous, symbol, result, quote, now):
    state = deepcopy(previous or {})
    events = []
    day = market_trading_date(now, "US")
    bounds = session_bounds("US", day)
    cutoff = bounds[1] - timedelta(hours=CONFIG.stop_before_close_hours) if bounds else None
    price = quote_value(quote, now)
    state.update(
        symbol=symbol,
        calculated_at=now.isoformat(),
        cutoff=cutoff.isoformat() if cutoff else None,
        stopped=not bounds or now < bounds[0] or now >= cutoff,
        current_price=price,
        quote_time=quote.event_time.isoformat() if quote and quote.event_time else None,
    )
    position = state.get("position")

    def event(kind, reason, **extra):
        events.append(
            dict(
                kind=kind,
                reason=reason,
                at=now.isoformat(),
                symbol=symbol,
                data_time=state["quote_time"],
                rule_version=VERSION,
                **extra,
            )
        )

    if state.get("trading_date") != day.isoformat() and not position:
        state["confirmations"], state["used_processes"], state["consumed_windows"] = {}, [], []
    state["trading_date"] = day.isoformat()
    healthy = price is not None
    if state.get("healthy") != healthy:
        event("data", "行情恢复" if healthy else "行情异常：暂停新进场，保留最后有效价格")
    state["healthy"] = healthy
    if position:
        side = position["side"]
        due = now >= dt(position["cutoff"])
        # Never substitute next-day or post-cutoff quotes for a missed planned exit.
        usable = price is not None and quote.event_time <= dt(position["cutoff"])
        if usable:
            position.update(last_price=price, last_price_at=quote.event_time.isoformat())
        exit_price = position["last_price"] if due else price
        reason = None
        if due:
            reason = "当日停止交易时间清仓"
        elif price is not None:
            risk = abs(position["entry_price"] - position["invalidation"])
            gain = side * (price - position["entry_price"])
            position["peak_gain"] = max(position["peak_gain"], gain)
            if side * (price - position["protection"]) <= 0:
                reason = "结构失效或保护位触及"
            elif position["target"] is not None and side * (price - position["target"]) >= 0:
                reason = "到达目标"
            elif (
                now - dt(position["entry_at"]) >= timedelta(minutes=CONFIG.no_progress_minutes)
                and gain < risk * CONFIG.minimum_progress_r
            ):
                reason = "持有超时且未有效推进"
            elif position["peak_gain"] >= CONFIG.protect_after_r * risk:
                protected = position["entry_price"] + side * (position["peak_gain"] - CONFIG.giveback_r * risk)
                if side * (protected - position["protection"]) > 0:
                    position["protection"] = protected
                    if not position.get("protection_active"):
                        position["protection_active"] = True
                        event("hold", "浮盈回撤保护已启动", trade_id=position["id"])
                if side * (price - position["protection"]) <= 0:
                    reason = "浮盈回撤保护"
        if reason:
            estimated = due and (
                not usable
                or abs((dt(position["cutoff"]) - dt(position["last_price_at"])).total_seconds())
                > CONFIG.quote_age_seconds
            )
            position.update(
                exit_price=exit_price,
                exit_at=now.isoformat(),
                exit_price_at=(position["last_price_at"] if due else quote.event_time.isoformat()),
                planned_exit_at=position["cutoff"] if due else now.isoformat(),
                exit_reason=reason,
                estimated=estimated,
                anomaly="截止行情缺失或重启后补记" if estimated else None,
                return_pct=side * (exit_price - position["entry_price"]) / position["entry_price"] * 100,
                duration_seconds=(now - dt(position["entry_at"])).total_seconds(),
            )
            event("exit", reason, trade=deepcopy(position), trade_id=position["id"])
            state["position"] = None
        else:
            position["return_pct"] = (
                side * (position["last_price"] - position["entry_price"]) / position["entry_price"] * 100
            )
    opportunities = (
        ((result or {}).get("opportunities") or {}) if result and result["trading_date"] == day.isoformat() else {}
    )
    plans = [plan(b, result, price, now) for b in opportunities.get("branches", [])]
    state["plans"] = plans
    # Freeze first observed confirmation, even if no position is opened.
    evidence = state.setdefault("confirmations", {})
    for item in plans:
        if item["confirmed_at"] and item["structure_id"] not in evidence:
            evidence[item["structure_id"]] = deepcopy(item)
            event("confirmed", "首次观察到形态确认", evidence=deepcopy(item))
    data_ok = bool(
        result
        and result["trading_date"] == day.isoformat()
        and 0 <= (now - dt(result["as_of"])).total_seconds() <= 75
        and not opportunities.get("reference", True)
    )
    used = state.setdefault("used_processes", [])
    windows = state.setdefault("consumed_windows", [])
    for item in plans:
        if state["stopped"]:
            item.update(executable=False, execution_reason="今日已停止进场或尚未开盘")
        elif position:
            item.update(executable=False, execution_reason="本周期已有虚拟持仓，禁止重复进场或反手")
        elif item["process_id"] in used or any(
            w["direction"] == item["direction"]
            and w["family"] == ("box" if item["kind"].startswith("box") else "trend")
            and dt(item.get("started_at", item["confirmed_at"])) < dt(w["end"])
            and dt(item["expires_at"]) > dt(w["start"])
            for w in windows
        ):
            item.update(executable=False, execution_reason="本过程已模拟交易，等待独立新机会")
        elif not data_ok:
            item.update(executable=False, execution_reason="闭合分钟数据不足或延迟")
    if not position and not state["stopped"] and data_ok:
        chosen = next((p for p in plans if p["executable"]), None)
        if chosen:
            used.append(chosen["process_id"])
            windows.append(
                dict(
                    direction=chosen["direction"],
                    family="box" if chosen["kind"].startswith("box") else "trend",
                    start=chosen.get("started_at", chosen["confirmed_at"]),
                    end=chosen["expires_at"],
                )
            )
            position = dict(
                id=f"{symbol}:{chosen['process_id']}",
                symbol=symbol,
                trading_date=day.isoformat(),
                side=1 if chosen["direction"] == "bullish" else -1,
                kind=chosen["kind"],
                opportunity_id=chosen["structure_id"],
                process_id=chosen["process_id"],
                version=VERSION,
                entry_price=price,
                entry_at=now.isoformat(),
                entry_price_at=quote.event_time.isoformat(),
                invalidation=chosen["invalidation"],
                protection=chosen["invalidation"],
                target=chosen["target"],
                cutoff=cutoff.isoformat(),
                evidence=deepcopy(evidence[chosen["structure_id"]]),
                entry_evidence=deepcopy(chosen),
                peak_gain=0,
                last_price=price,
                last_price_at=quote.event_time.isoformat(),
                return_pct=0,
            )
            state["position"] = position
            for item in plans:
                item.update(executable=False, execution_reason="已模拟持有，禁止重复进场或反手")
            event(
                "entry",
                "模拟做多进场" if position["side"] == 1 else "模拟做空进场",
                trade=deepcopy(position),
                trade_id=position["id"],
            )
    return state, events


def statistics(trades):
    def group(rows):
        values = [r["return_pct"] for r in rows]
        wins, losses = [x for x in values if x > 0], [x for x in values if x < 0]
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        return dict(
            count=len(rows),
            win_rate=len(wins) / len(rows) * 100 if rows else None,
            average_return=mean(values),
            average_win=mean(wins),
            average_loss=mean(losses),
            average_duration=mean([r["duration_seconds"] for r in rows]),
        )

    return [
        dict(label=label, **group(rows))
        for label, rows in [
            ("正常报价", [r for r in trades if not r["estimated"]]),
            ("估算退出", [r for r in trades if r["estimated"]]),
        ]
    ] + [
        dict(
            label=f"{kind}/{side}",
            **group([r for r in trades if r["kind"] == kind and r["side"] == side and not r["estimated"]]),
        )
        for kind in ("box_breakout", "box_retest", "trend_recovery")
        for side in (1, -1)
    ]
