"""Underlying-only paper execution. Pure transitions, immutable entry evidence."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.intraday_options.rules import RULES, SIMULATION_VERSION, START_KINDS, policy, entry_interval, plan_order

VERSION = SIMULATION_VERSION


@dataclass(frozen=True)
class ExecutionConfig:
    quote_age_seconds: int = 30
    no_progress_minutes: int = 35
    minimum_progress_r: float = 0.25
    breakeven_after_r: float = 1.2
    trail_after_r: float = 2.0
    trail_giveback_r: float = 1.0
    trail_bars: int = 15
    entry_stop_before_close_minutes: int = 90
    exit_stop_before_close_minutes: int = 10
    max_daily_entries: int = 2
    cooldown_minutes: int = 10
    stop_cooldown_minutes: int = 20
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


def target_space(price, invalidation, target, side, required, settings):
    """Return unrounded quote-time economics; equality qualifies despite binary price arithmetic."""
    risk = (price - invalidation) * side if price is not None and invalidation is not None else None
    risk_return = risk / price if risk is not None and price > 0 else None
    reward = (target - price) * side if price is not None and target is not None else None
    fraction = reward / price if reward is not None and price > 0 else None
    rr = reward / risk if reward is not None and risk and risk > 0 else None
    reasons = []
    if price is not None:
        if risk is None or not math.isfinite(risk) or risk <= 0:
            reasons.append("初始风险无效：报价已越过失效位或缺少失效位")
        elif required and target is None:
            reasons.append("固定目标缺失")
        elif reward is not None:
            if reward <= 0:
                reasons.append("目标已越过")
            else:
                if fraction < settings.minimum_return and not math.isclose(fraction, settings.minimum_return, rel_tol=1e-10):
                    reasons.append("剩余止盈幅度不足")
                if rr < settings.minimum_rr and not math.isclose(rr, settings.minimum_rr, rel_tol=1e-10):
                    reasons.append("计划盈亏比不足")
    return dict(initial_risk=risk, initial_risk_return=risk_return, remaining_space=reward, remaining_return=fraction,
                reward_risk=rr, space_rejections=reasons, min_target_return=settings.minimum_return,
                min_reward_risk=settings.minimum_rr)


def _context_rejection(kind, side, result, cfg):
    """Check causal VWAP, SPY market alignment, and relative-strength gates when context is present."""
    market_context = result.get("market_context")
    has_market_context = "market_context" in result
    spy_context = result.get("spy_context")
    has_spy_context = "spy_context" in result
    needs_vwap = cfg.require_vwap and kind in ("opening_breakout", "midday_wave_breakout", "box_breakout")
    needs_spy = cfg.require_spy_alignment and kind in ("opening_breakout", "midday_wave_breakout")

    if needs_vwap and has_market_context:
        if not market_context or market_context.get("vwap") is None:
            return "缺少当日有效VWAP，暂不执行突破进场"
        if (market_context["last_close"] - market_context["vwap"]) * side <= 0:
            return "价格未位于当日VWAP顺向侧"

    if needs_spy and has_spy_context:
        if not spy_context or spy_context.get("vwap") is None or spy_context.get("as_of") is None:
            return "缺少同期SPY基准数据，暂不进场"
        if result.get("as_of") and abs((dt(result["as_of"]) - dt(spy_context["as_of"])).total_seconds()) > 120:
            return "SPY基准分钟数据未对齐，暂不进场"
        if (spy_context["last_close"] - spy_context["vwap"]) * side <= 0:
            return "SPY大盘未位于当日VWAP顺向侧"
        if cfg.min_relative_strength > 0 and result.get("symbol") != "SPY.US":
            ret_key = "open_return" if kind == "opening_breakout" else "return_20m"
            sym_ret = (market_context or {}).get(ret_key)
            spy_ret = spy_context.get(ret_key)
            if sym_ret is None or spy_ret is None:
                return "缺少相对SPY强弱基准数据，暂不进场"
            rel = (sym_ret - spy_ret) * side
            if rel < cfg.min_relative_strength and not math.isclose(rel, cfg.min_relative_strength, rel_tol=1e-10):
                return f"相对SPY强弱不足{cfg.min_relative_strength * 100:.2f}%，过滤弱势突破"
    return None


def plan(branch, result, price, now, quote_time=None, previous_plan=None, settings=None):
    cfg = settings or policy()
    side = 1 if branch["direction"] == "bullish" else -1
    kind = branch["kind"]
    rule = RULES[kind]
    interval = entry_interval(branch)
    needs_vwap = cfg.require_vwap and kind in ("opening_breakout", "midday_wave_breakout", "box_breakout")
    needs_spy = cfg.require_spy_alignment and kind in ("opening_breakout", "midday_wave_breakout")
    quote_floor = entry_quote_floor(branch, previous_plan, result.get("as_of"))
    if quote_floor and cfg.use_pivot_target and result.get("target_evidence_at"):
        quote_floor = max(quote_floor, dt(result["target_evidence_at"]))
    market_context = result.get("market_context")
    if quote_floor and (needs_vwap or needs_spy) and market_context and market_context.get("evidence_at"):
        quote_floor = max(quote_floor, dt(market_context["evidence_at"]))
    spy_context = result.get("spy_context")
    if quote_floor and needs_spy and spy_context and spy_context.get("evidence_at"):
        quote_floor = max(quote_floor, dt(spy_context["evidence_at"]))

    previous_plan = previous_plan or {}
    if cfg.use_pivot_target:
        # Confirmed pivots are raw intraday prices, the same basis as execution quotes.
        candidates = [
            p["price"]
            for p in result.get("execution_pivots", [])
            if p["kind"] == ("high" if side == 1 else "low")
            and dt(p["confirmed_at"]) <= now
            and price is not None
            and (p["price"] - price) * side >= 0
        ]
        target = min(candidates, key=lambda p: (p - price) * side) if candidates else branch.get("measurement_target")
        source = "已确认结构位" if candidates else "箱体高度测量估计" if target else "未知"
        if target and not candidates and kind == "opening_breakout":
            source = "开盘区间高度测量估计"
        elif target and not candidates and kind == "midday_wave_breakout":
            source = "盘中整理高度测量估计"
        # Keep a rejected nearby obstacle through quote changes, including a move past it.
        locked = previous_plan.get("target_limit")
        lock_source = previous_plan.get("target_limit_source")
        exhausted = previous_plan.get("target_exhausted", False)
        timely = quote_time is None or (quote_floor is not None and quote_time >= quote_floor)
        if timely and locked is not None and price is not None and (locked - price) * side <= 0:
            exhausted = True
        if locked is not None and lock_source == "已确认结构位" and not any(
            p["price"] == locked and p["kind"] == ("high" if side > 0 else "low")
            for p in result.get("execution_pivots", [])
        ):
            exhausted = True
        if locked is not None and (target is None or (target - locked) * side >= 0):
            target, source = locked, lock_source
        required = kind in START_KINDS or kind.startswith("box")
    else:
        target, source = None, "移动止损跟踪"
        locked, lock_source, exhausted, required = None, None, False, False

    economics = target_space(price, branch.get("invalidation"), target, side, required, cfg)
    context_reason = _context_rejection(kind, side, result, cfg)
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
    elif economics["initial_risk"] is None or economics["initial_risk"] <= 0:
        reason = economics["space_rejections"][0]
    elif not interval[0] <= price <= interval[1]:
        reason = "形态已确认，当前报价不在冻结执行区间（不补记触发价成交）"
    elif rule.max_risk_atr is not None and (price - branch["invalidation"]) * side > rule.max_risk_atr * branch["atr"]:
        reason = f"当前报价到结构失效位超过{rule.max_risk_atr:g} ATR，风险距离过大"
    elif (
        cfg.minimum_risk_return > 0
        and economics["initial_risk_return"] is not None
        and economics["initial_risk_return"] < cfg.minimum_risk_return
        and not math.isclose(economics["initial_risk_return"], cfg.minimum_risk_return, rel_tol=1e-10)
    ):
        reason = f"初始风险幅度不足{cfg.minimum_risk_return * 100:.2f}%，过滤低波动噪音"
    elif context_reason:
        reason = context_reason
    elif exhausted:
        reason = "原目标已越过或已失效，等待新的独立机会"
    elif economics["space_rejections"]:
        reason = "、".join(economics["space_rejections"])
    if cfg.use_pivot_target and target is not None and (
        reason == "可以模拟进场" or reason == "、".join(economics["space_rejections"])
    ):
        locked, lock_source = target, source
    return {
        **deepcopy(branch),
        "process_id": branch.get("process_id", branch["structure_id"]),
        "entry_low": interval[0],
        "entry_high": interval[1],
        "target": target,
        "target_source": source,
        "target_limit": locked,
        "target_limit_source": lock_source,
        "target_exhausted": exhausted,
        "entry_quote": price,
        "entry_quote_time": quote_time.isoformat() if quote_time else None,
        **economics,
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
    if window["direction"] == item["direction"] and (item["kind"] in START_KINDS or window.get("kind") in START_KINDS):
        if item["kind"] == "midday_wave_breakout":
            anchor = item.get("structure_end") or item.get("started_at") or item["confirmed_at"]
        else:
            anchor = item.get("structure_start") or item.get("formation_start") or item["confirmed_at"]
        # V1 windows froze only the interval; its end bounds the unknown entry time.
        return dt(anchor) <= dt(window.get("entered_at") or window["end"])
    if window["direction"] != item["direction"] or window["family"] != family:
        return False
    if family == "trend" and item.get("structure_start") and window.get("structure_end"):
        # A fresh counter-move must begin after both the traded structure and entry.
        # Older/same structures stay consumed; overlapping lifetimes alone are not identity.
        return dt(item["structure_start"]) <= max(dt(window["structure_end"]), dt(window["entered_at"]))
    # Legacy persisted windows have no structure evidence: retain their old protection.
    return (dt(item.get("started_at", item["confirmed_at"])) < dt(window["end"])
            and dt(item["expires_at"]) > dt(window["start"]))


def transition(previous, symbol, result, quote, now, settings=None):
    state = deepcopy(previous or {})
    previous_calculation = dt(state.get("calculated_at"))
    previous_healthy = state.get("healthy", False)
    events = []
    day = market_trading_date(now, "US")
    bounds = session_bounds("US", day)
    entry_cutoff = bounds[1] - timedelta(minutes=CONFIG.entry_stop_before_close_minutes) if bounds else None
    exit_cutoff = bounds[1] - timedelta(minutes=CONFIG.exit_stop_before_close_minutes) if bounds else None
    phase = (
        "closed"
        if not bounds or now >= bounds[1]
        else "preopen" if now < bounds[0] else "stopped" if now >= entry_cutoff else "active"
    )
    price = quote_value(quote, now)
    state.update(
        symbol=symbol,
        calculated_at=now.isoformat(),
        cutoff=entry_cutoff.isoformat() if entry_cutoff else None,
        exit_cutoff=exit_cutoff.isoformat() if exit_cutoff else None,
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

    new_day = state.get("trading_date") != day.isoformat()
    if new_day:
        state["daily_entry_count"] = 0
        state["last_exit_at"] = None
        state["last_stop_by_side"] = {}
        if not position:
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
            reason = "当日收盘前清仓"
        elif price is not None:
            risk = abs(position["entry_price"] - position["invalidation"])
            gain = side * (price - position["entry_price"])
            position["peak_gain"] = max(position["peak_gain"], gain)
            if side * (price - position["protection"]) <= 0:
                reason = "移动止损或保护位触及" if position.get("protection_active") else "结构失效或保护位触及"
            elif position["target"] is not None and side * (price - position["target"]) >= 0:
                reason = "到达目标"
            elif (
                now - dt(position["entry_at"]) >= timedelta(minutes=CONFIG.no_progress_minutes)
                and gain < risk * CONFIG.minimum_progress_r
            ):
                reason = "持有超时且未有效推进"
            elif risk > 0:
                candidate = None
                stage = None
                if position["peak_gain"] >= CONFIG.trail_after_r * risk:
                    giveback_level = position["entry_price"] + side * (
                        position["peak_gain"] - CONFIG.trail_giveback_r * risk
                    )
                    recent = [
                        b
                        for b in (result or {}).get("recent_bars", [])
                        if result
                        and result.get("trading_date") == position.get("trading_date")
                        and dt(b["close_at"]) > dt(position["entry_at"])
                    ][-CONFIG.trail_bars:]
                    if recent:
                        struct_level = (
                            min(b["low"] for b in recent) if side == 1 else max(b["high"] for b in recent)
                        )
                        candidate = (
                            min(struct_level, giveback_level) if side == 1 else max(struct_level, giveback_level)
                        )
                        candidate = (
                            max(position["entry_price"], candidate)
                            if side == 1
                            else min(position["entry_price"], candidate)
                        )
                    else:
                        candidate = giveback_level
                    stage = "trailing"
                elif position["peak_gain"] >= CONFIG.breakeven_after_r * risk:
                    candidate = position["entry_price"]
                    stage = "breakeven"
                if candidate is not None and side * (candidate - position["protection"]) > 0:
                    position["protection"] = candidate
                    if stage == "trailing" and position.get("protection_stage") != "trailing":
                        position["protection_active"] = True
                        position["protection_stage"] = "trailing"
                        event("hold", "浮盈已达2.0R，启动15分钟结构移动止损", trade_id=position["id"], side=side)
                    elif stage == "breakeven" and not position.get("protection_active"):
                        position["protection_active"] = True
                        position["protection_stage"] = "breakeven"
                        event("hold", "浮盈已达1.2R，保护位上移至成本价", trade_id=position["id"], side=side)
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
            if position.get("trading_date") == day.isoformat():
                state["last_exit_at"] = now.isoformat()
                if position["return_pct"] < 0:
                    state.setdefault("last_stop_by_side", {})[str(side)] = now.isoformat()
            elif new_day:
                state["confirmations"], state["used_processes"], state["consumed_windows"] = {}, [], []
            state["position"] = None
        else:
            position["return_pct"] = (
                side * (position["last_price"] - position["entry_price"]) / position["entry_price"] * 100
            )
    opportunities = (
        ((result or {}).get("opportunities") or {}) if result and result["trading_date"] == day.isoformat() else {}
    )
    limits = {k: v for k, v in state.get("target_limits", {}).items() if dt(v["expires_at"]) > now}
    previous_plans = {**limits, **{p["structure_id"]: p for p in state.get("plans", [])}}
    plan_result = result if not result or "symbol" in result else {**result, "symbol": symbol}
    plans = [plan(b, plan_result, price, now, quote.event_time if price is not None else None,
                  previous_plans.get(b["structure_id"]), settings)
             for b in opportunities.get("branches", [])]
    for item in plans:
        if item["target_limit"] is not None and dt(item["expires_at"]) > now:
            limits[item["structure_id"]] = {k: item[k] for k in ("target_limit", "target_limit_source",
                                                                  "target_exhausted", "expires_at")}
    state["target_limits"] = limits
    # Persist the first observed geometry even when price has not yet broken the level.
    # A late historical revision cannot move that level or widen its projected target.
    frozen_levels = {k: v for k, v in state.get("start_levels", {}).items() if dt(v["expires_at"]) > now}
    for identity, level in opportunities.get("start_levels", {}).items():
        if dt(level["expires_at"]) > now:
            frozen_levels.setdefault(identity, dict(level))
    state["start_levels"] = frozen_levels
    for item in plans:
        identity = item["structure_id"]
        if identity not in frozen_levels:
            continue
        original = frozen_levels[identity]
        current = opportunities.get("start_levels", {}).get(identity, {})
        if any(original.get(k) != current.get(k) for k in ("atr", "width", "trigger")):
            item.update(executable=False, execution_reason="历史修订改变已冻结结构，等待独立新机会")
        elif original.setdefault("first_break", item["started_at"]) != item["started_at"]:
            item.update(executable=False, execution_reason="历史修订改变首次突破时刻，原过程不延长")
    state["plans"] = plans
    data_ok = bool(
        result
        and result["trading_date"] == day.isoformat()
        and bounds
        and bounds[0] <= dt(result["as_of"]) <= now
        and 0 <= (now - dt(result["as_of"])).total_seconds() <= 75
    )
    def data_ready(item):
        return data_ok and (not opportunities.get("reference", True) or item["kind"] == "opening_breakout")

    # Freeze first observed confirmation, even if no position is opened.
    evidence = state.setdefault("confirmations", {})
    for item in plans:
        if (
            phase == "active"
            and data_ready(item)
            and item["confirmed_at"]
            and not item.get("superseded_by")
            and bounds[0] <= dt(item["confirmed_at"]) <= now
            and item["structure_id"] not in evidence
        ):
            evidence[item["structure_id"]] = deepcopy(item)
            event("confirmed", "首次观察到形态确认", evidence=deepcopy(item))
    used = state.setdefault("used_processes", [])
    windows = state.setdefault("consumed_windows", [])
    daily_entries = int(state.get("daily_entry_count") or 0)
    last_exit = dt(state.get("last_exit_at"))
    last_stop_map = state.get("last_stop_by_side") or {}
    for item in plans:
        if item["executable"] and item["structure_id"] not in evidence:
            item.update(executable=False, execution_reason="等待交易时段内有效确认")
        # Display validity belongs to this branch and ignores ownership/process consumption.
        item["opportunity_valid"] = item["executable"] and data_ready(item) and not state["stopped"]
        item["opportunity_reason"] = (
            "今日已停止进场或尚未开盘"
            if state["stopped"]
            else "闭合分钟数据不足或延迟" if not data_ready(item) else item["execution_reason"]
        )
        side_key = "1" if item["direction"] == "bullish" else "-1"
        last_stop = dt(last_stop_map.get(side_key))
        if state["stopped"]:
            item.update(executable=False, execution_reason="今日已停止进场或尚未开盘")
        elif position and item["executable"]:
            item.update(executable=False, execution_reason="本周期已有虚拟持仓，禁止重复进场或反手")
        elif item["executable"] and (item["process_id"] in used or any(consumed_structure(item, w) for w in windows)):
            item.update(executable=False, execution_reason="本过程已模拟交易，等待独立新机会")
        elif item["executable"] and daily_entries >= CONFIG.max_daily_entries:
            item.update(
                executable=False,
                execution_reason=f"今日该标的已达最大开仓次数上限（{CONFIG.max_daily_entries}笔）",
            )
        elif (
            item["executable"]
            and last_exit is not None
            and (now - last_exit) < timedelta(minutes=CONFIG.cooldown_minutes)
        ):
            item.update(executable=False, execution_reason=f"退场后{CONFIG.cooldown_minutes}分钟冷却中")
        elif (
            item["executable"]
            and last_stop is not None
            and (now - last_stop) < timedelta(minutes=CONFIG.stop_cooldown_minutes)
        ):
            item.update(executable=False, execution_reason=f"同方向止损后{CONFIG.stop_cooldown_minutes}分钟冷却中")
        elif not data_ready(item):
            item.update(executable=False, execution_reason="闭合分钟数据不足或延迟")
    if not position and not state["stopped"] and data_ok:
        chosen = min((p for p in plans if p["executable"]), key=plan_order, default=None)
        if chosen:
            used.append(chosen["process_id"])
            windows.append(
                dict(
                    kind=chosen["kind"],
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
                cutoff=exit_cutoff.isoformat(),
                evidence=deepcopy(evidence[chosen["structure_id"]]),
                entry_evidence=deepcopy(chosen),
                peak_gain=0,
                last_price=price,
                last_price_at=quote.event_time.isoformat(),
                return_pct=0,
            )
            state["position"] = position
            state["daily_entry_count"] = daily_entries + 1
            state["entered_opportunity_id"] = chosen["structure_id"]
            for item in plans:
                if item["executable"]:
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
