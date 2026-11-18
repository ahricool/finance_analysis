"""Underlying-only paper execution. Pure transitions, immutable entry evidence."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.intraday_options.rules import RULES, SIMULATION_VERSION, entry_interval, plan_order

VERSION = SIMULATION_VERSION


@dataclass(frozen=True)
class ExecutionConfig:
    quote_age_seconds: int = 30
    no_progress_minutes: int = 20
    minimum_progress_r: float = 0.25
    protect_after_r: float = 1.0
    giveback_r: float = 0.5
    stop_before_close_hours: int = 2
    workers: int = 4
    cutoff_processing_grace_seconds: int = 30
    data_alert_seconds: int = 30
    data_recovery_seconds: int = 15


CONFIG = ExecutionConfig()


def dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def quote_issue(quote, now):
    if not quote or quote.timestamp_kind == "received" or not quote.event_time or not quote.received_at:
        return "报价缺失或时间字段无效"
    if quote.trading_date != market_trading_date(now, "US"):
        return "报价交易日不匹配"
    ages = [(now - t).total_seconds() for t in (quote.event_time, quote.received_at)]
    if min(ages) < 0:
        return "报价或接收时间超前"
    if max(ages) > CONFIG.quote_age_seconds:
        return "报价或接收时间已过期"
    bounds = session_bounds("US", quote.trading_date)
    if not bounds or not bounds[0] <= quote.event_time < bounds[1]:
        return "报价不属于正常交易时段"
    price = float(quote.last_price or 0)
    return None if math.isfinite(price) and price > 0 else "报价价格无效"


def quote_value(quote, now):
    return float(quote.last_price) if quote_issue(quote, now) is None else None


def monitor_data(state, active, issue, quote, now, event):
    """Debounce messages only. Execution always uses the strict current quote check."""
    if not active:
        state["data_monitor"] = None
        return
    monitor = state.get("data_monitor") or {}
    if monitor.get("day") != state["trading_date"]:
        monitor = {"day": state["trading_date"], "alerted": False}
    last_check = dt(monitor.get("checked_at"))
    if last_check and not 0 <= (now - last_check).total_seconds() <= CONFIG.data_recovery_seconds:
        # A processing gap is not evidence of continuously valid/invalid quotes.
        monitor.pop("issue_since", None)
        monitor.pop("recovery_since", None)
    monitor["checked_at"] = now.isoformat()
    state["data_monitor"] = monitor
    since_key = "issue_since" if issue else "recovery_since"
    monitor.pop("recovery_since" if issue else "issue_since", None)
    monitor.setdefault(since_key, now.isoformat())
    delay = CONFIG.data_alert_seconds if issue else CONFIG.data_recovery_seconds
    if (now - dt(monitor[since_key])).total_seconds() < delay or monitor["alerted"] == bool(issue):
        return
    monitor["alerted"] = bool(issue)
    event(
        "data",
        f"行情异常：{issue}，暂停新进场" if issue else "行情恢复：有效报价已持续稳定",
        issue=issue,
        since=monitor[since_key],
        quote_age_seconds=(now - quote.event_time).total_seconds() if quote and quote.event_time else None,
        received_age_seconds=(now - quote.received_at).total_seconds() if quote and quote.received_at else None,
    )


def entry_quote_floor(branch, previous_plan, minute_as_of):
    if not branch.get("confirmed_at"):
        return None
    latest = dt(branch.get("execution_evidence_at") or branch["confirmed_at"])
    # Only an already observed, uninterrupted shape can reuse its earlier quote floor.
    # A quote outside the interval affects execution, not continuity of the shape.
    if (
        previous_plan
        and previous_plan.get("status") == "confirmed"
        and not previous_plan.get("breakout_rejection")
        and not previous_plan.get("superseded_by")
        and previous_plan.get("entry_quote_not_before")
        and branch.get("confirmation_run_available_at")
        and all(previous_plan.get(k) == branch.get(k) for k in ("confirmed_at", "trigger", "invalidation", "atr"))
    ):
        # A tick can miss both the original and its correction. A post-close version
        # of a minute we never observed cannot prove continuity before its receipt.
        if minute_as_of and previous_plan.get("minute_as_of") and (
            dt(previous_plan["minute_as_of"]) < dt(minute_as_of) < latest
        ):
            return latest
        return max(dt(previous_plan["entry_quote_not_before"]), dt(branch["confirmation_run_available_at"]))
    return max(latest, dt(branch["confirmed_at"]))


def plan(branch, result, price, now, quote_time=None, previous_plan=None):
    side = 1 if branch["direction"] == "bullish" else -1
    rule = RULES[branch["kind"]]
    interval = entry_interval(branch)
    quote_floor = entry_quote_floor(branch, previous_plan, result.get("as_of"))
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
    if branch.get("superseded_by"):
        reason = "已有后续独立结构，旧候选证据保留但不再进场"
    elif branch.get("breakout_rejection"):
        reason = branch["breakout_rejection"]
    elif branch["status"] != "confirmed":
        reason = {"forming": "形态尚未确认", "extended": "形态已确认但过度延伸，禁止追价",
                  "invalidated": "冻结结构已失效，等待独立新机会", "expired": "原机会已到期"}[branch["status"]]
    elif not branch["confirmed_at"] or dt(branch["confirmed_at"]) > now:
        reason = "形态确认时间无效"
    elif now >= dt(branch["expires_at"]):
        reason = "机会已过期"
    elif price is None:
        reason = "报价缺失、过期或时间异常"
    elif quote_time is not None and quote_time < quote_floor:
        reason = ("等待确认依据到达后的有效报价" if quote_time >= dt(branch["confirmed_at"])
                  else "等待确认后的有效报价")
    elif (price - branch["invalidation"]) * side <= 0:
        reason = "最新价格已越过失效位"
    elif not interval[0] <= price <= interval[1]:
        reason = "形态已确认，当前报价不在冻结执行区间（不补记触发价成交）"
    elif rule.max_risk_atr is not None and (price - branch["invalidation"]) * side > rule.max_risk_atr * branch["atr"]:
        reason = f"当前报价到结构失效位超过{rule.max_risk_atr:g} ATR，风险距离过大"
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
        "entry_quote_not_before": quote_floor.isoformat() if quote_floor else None,
        "rule_version": VERSION,
        "max_risk_atr": rule.max_risk_atr,
        "analysis_coverage": {
            key: deepcopy(result.get("opportunities", {}).get(key))
            for key in ("version", "required_minutes", "recent_available_bars", "recent_missing_bars",
                        "missing_bars", "filled_bars", "filled_minutes")
        },
        "age_seconds": (now - dt(branch["confirmed_at"])).total_seconds() if branch["confirmed_at"] else None,
        "executable": reason == "可以模拟进场",
        "execution_reason": reason,
    }


def consumed_structure(item, window):
    family = "box" if item["kind"].startswith("box") else "trend"
    if window["direction"] != item["direction"] or window["family"] != family:
        return False
    if family == "trend" and item.get("structure_start") and window.get("structure_end"):
        # A fresh counter-move must begin after both the traded structure and entry.
        # Older/same structures stay consumed; overlapping lifetimes alone are not identity.
        return dt(item["structure_start"]) <= max(dt(window["structure_end"]), dt(window["entered_at"]))
    # Legacy persisted windows have no structure evidence: retain their old protection.
    return (dt(item.get("started_at", item["confirmed_at"])) < dt(window["end"])
            and dt(item["expires_at"]) > dt(window["start"]))


def transition(previous, symbol, result, quote, now):
    state = deepcopy(previous or {})
    previous_calculation = dt(state.get("calculated_at"))
    previous_healthy = state.get("healthy", False)
    events = []
    day = market_trading_date(now, "US")
    bounds = session_bounds("US", day)
    cutoff = bounds[1] - timedelta(hours=CONFIG.stop_before_close_hours) if bounds else None
    phase = (
        "closed"
        if not bounds or now >= bounds[1]
        else "preopen" if now < bounds[0] else "stopped" if now >= cutoff else "active"
    )
    price = quote_value(quote, now)
    state.update(
        symbol=symbol,
        calculated_at=now.isoformat(),
        cutoff=cutoff.isoformat() if cutoff else None,
        stopped=phase != "active",
        session_phase=phase,
        session_open=bounds[0].isoformat() if bounds else None,
        current_price=price,
        quote_time=quote.event_time.isoformat() if quote and quote.event_time else None,
        entered_opportunity_id=None,
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
    state["data_issue"] = quote_issue(quote, now) if phase == "active" else None
    monitor_data(state, phase == "active", state["data_issue"], quote, now, event)
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
                        event("hold", "浮盈回撤保护已启动", trade_id=position["id"], side=side)
                if side * (price - position["protection"]) <= 0:
                    reason = "浮盈回撤保护"
        if reason:
            estimated = due and (
                not previous_healthy
                or previous_calculation is None
                or not 0 <= (now - previous_calculation).total_seconds() <= CONFIG.cutoff_processing_grace_seconds
                or not 0 <= (now - dt(position["cutoff"])).total_seconds() <= CONFIG.cutoff_processing_grace_seconds
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
    previous_plans = {p["structure_id"]: p for p in state.get("plans", [])}
    plans = [plan(b, result, price, now, quote.event_time if price is not None else None,
                  previous_plans.get(b["structure_id"]))
             for b in opportunities.get("branches", [])]
    state["plans"] = plans
    data_ok = bool(
        result
        and result["trading_date"] == day.isoformat()
        and bounds
        and bounds[0] <= dt(result["as_of"]) <= now
        and 0 <= (now - dt(result["as_of"])).total_seconds() <= 75
        and not opportunities.get("reference", True)
    )
    # Freeze first observed confirmation, even if no position is opened.
    evidence = state.setdefault("confirmations", {})
    for item in plans:
        if (
            phase == "active"
            and data_ok
            and item["confirmed_at"]
            and not item.get("superseded_by")
            and bounds[0] <= dt(item["confirmed_at"]) <= now
            and item["structure_id"] not in evidence
        ):
            evidence[item["structure_id"]] = deepcopy(item)
            event("confirmed", "首次观察到形态确认", evidence=deepcopy(item))
    used = state.setdefault("used_processes", [])
    windows = state.setdefault("consumed_windows", [])
    for item in plans:
        if item["executable"] and item["structure_id"] not in evidence:
            item.update(executable=False, execution_reason="等待交易时段内有效确认")
        # Display validity belongs to this branch and ignores ownership/process consumption.
        item["opportunity_valid"] = item["executable"] and data_ok and not state["stopped"]
        item["opportunity_reason"] = (
            "今日已停止进场或尚未开盘"
            if state["stopped"]
            else "闭合分钟数据不足或延迟" if not data_ok else item["execution_reason"]
        )
        if state["stopped"]:
            item.update(executable=False, execution_reason="今日已停止进场或尚未开盘")
        elif position:
            item.update(executable=False, execution_reason="本周期已有虚拟持仓，禁止重复进场或反手")
        elif item["process_id"] in used or any(consumed_structure(item, w) for w in windows):
            item.update(executable=False, execution_reason="本过程已模拟交易，等待独立新机会")
        elif not data_ok:
            item.update(executable=False, execution_reason="闭合分钟数据不足或延迟")
    if not position and not state["stopped"] and data_ok:
        chosen = min((p for p in plans if p["executable"]), key=plan_order, default=None)
        if chosen:
            used.append(chosen["process_id"])
            windows.append(
                dict(
                    direction=chosen["direction"],
                    family="box" if chosen["kind"].startswith("box") else "trend",
                    start=chosen.get("started_at", chosen["confirmed_at"]),
                    end=chosen["expires_at"],
                    structure_start=chosen.get("structure_start"),
                    structure_end=chosen.get("structure_end"),
                    entered_at=now.isoformat(),
                )
            )
            position = dict(
                id=f"{symbol}:{chosen['process_id']}",
                symbol=symbol,
                trading_date=day.isoformat(),
                side=1 if chosen["direction"] == "bullish" else -1,
                kind=chosen["kind"],
                confirmation_method=chosen.get("confirmation_method"),
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
            state["entered_opportunity_id"] = chosen["structure_id"]
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
        for kind in RULES
        for side in (1, -1)
    ]
