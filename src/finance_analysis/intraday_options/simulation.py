"""Underlying-only paper execution. Pure transitions, immutable entry evidence."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.intraday_options.config import BENCHMARK_SYMBOL_SET
from finance_analysis.intraday_options.rules import (
    RULES,
    SIMULATION_VERSION,
    START_KINDS,
    direction_allowed,
    entry_interval,
    plan_order,
    policy,
    resolve_atr_exit_levels,
)

VERSION = SIMULATION_VERSION


@dataclass(frozen=True)
class ExecutionConfig:
    quote_age_seconds: int = 30
    no_progress_minutes: int = 90
    no_progress_underwater_only: bool = True
    minimum_progress_r: float = 0.25
    breakeven_after_r: float = 1.5
    trail_after_r: float = 2.5
    trail_giveback_r: float = 1.2
    trail_bars: int = 45
    entry_window_minutes: int = 120
    min_entry_before_close_minutes: int = 90
    exit_stop_before_close_minutes: int = 10
    max_daily_entries: int = 1
    cooldown_minutes: int = 30
    stop_cooldown_minutes: int = 60
    workers: int = 6
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
        and all(
            (
                previous_plan.get("structure_invalidation", previous_plan.get("invalidation"))
                if k == "invalidation"
                else previous_plan.get(k)
            )
            == branch.get(k)
            for k in ("confirmed_at", "trigger", "invalidation", "atr")
        )
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
    """Check causal direction, benchmark, gap, VWAP, open-move, efficiency, SPY, RS, leader rank, and breadth gates."""
    if kind == "opening_breakout" and not direction_allowed(side, cfg.opening_direction_mode):
        if cfg.opening_direction_mode == "long_only":
            return "当前策略仅允许做多开盘驱动，过滤空头方向"
        return "当前策略仅允许做空开盘驱动，过滤多头方向"
    if (
        kind == "opening_breakout"
        and cfg.exclude_benchmark_from_opening
        and result.get("symbol") in BENCHMARK_SYMBOL_SET
    ):
        return "基准指数ETF不参与开盘驱动模拟开仓"

    market_context = result.get("market_context")
    has_market_context = "market_context" in result
    spy_context = result.get("spy_context")
    has_spy_context = "spy_context" in result
    pool_rank = result.get("pool_rank_context")
    has_pool_rank = "pool_rank_context" in result
    daily_context = result.get("daily_context")
    has_daily_context = "daily_context" in result
    needs_vwap = cfg.require_vwap and kind in ("opening_breakout", "midday_wave_breakout", "box_breakout")
    needs_spy = cfg.require_spy_alignment and kind in ("opening_breakout", "midday_wave_breakout")
    needs_leader = kind in ("opening_breakout", "midday_wave_breakout")

    if kind == "opening_breakout" and cfg.min_gap_directional is not None and has_daily_context:
        gap_ret = (daily_context or {}).get("gap_return")
        if gap_ret is None:
            return "缺少昨收基准数据，无法校验隔夜跳空门槛"
        directional_gap = gap_ret * side
        if directional_gap < cfg.min_gap_directional and not math.isclose(
            directional_gap, cfg.min_gap_directional, rel_tol=1e-10
        ):
            return f"隔夜反向跳空过大（{gap_ret * 100:+.2f}%），过滤反跳空突破"

    if needs_vwap and has_market_context:
        if not market_context or market_context.get("vwap") is None:
            return "缺少当日有效VWAP，暂不执行突破进场"
        if (market_context["last_close"] - market_context["vwap"]) * side <= 0:
            return "价格未位于当日VWAP顺向侧"

    if needs_leader and cfg.min_open_move > 0 and has_market_context:
        sym_open = (market_context or {}).get("open_return")
        if sym_open is None:
            return "缺少开盘至今涨幅基准数据，暂不进场"
        directional_move = sym_open * side
        if directional_move < cfg.min_open_move and not math.isclose(
            directional_move, cfg.min_open_move, rel_tol=1e-10
        ):
            return f"日内相对开盘推进不足{cfg.min_open_move * 100:.2f}%，过滤窄幅波动"

    if kind == "opening_breakout" and cfg.opening_min_efficiency > 0 and has_market_context:
        open_eff = (market_context or {}).get("open_efficiency")
        if open_eff is None:
            return "缺少连续开盘路径效率基准数据，暂不进场"
        if open_eff < cfg.opening_min_efficiency and not math.isclose(
            open_eff, cfg.opening_min_efficiency, rel_tol=1e-10
        ):
            return f"开盘路径效率不足{cfg.opening_min_efficiency * 100:.0f}%，过滤锯齿震荡"

    spy_open_dir = None
    if needs_spy and has_spy_context:
        if not spy_context or spy_context.get("vwap") is None or spy_context.get("as_of") is None:
            return "缺少同期SPY基准数据，暂不进场"
        if result.get("as_of") and abs((dt(result["as_of"]) - dt(spy_context["as_of"])).total_seconds()) > 120:
            return "SPY基准分钟数据未对齐，暂不进场"
        if (spy_context["last_close"] - spy_context["vwap"]) * side <= 0:
            return "SPY大盘未位于当日VWAP顺向侧"
        spy_open = spy_context.get("open_return")
        if spy_open is not None:
            spy_open_dir = spy_open * side
        if cfg.min_relative_strength > 0 and result.get("symbol") != "SPY.US":
            sym_open = (market_context or {}).get("open_return")
            rs_open = (sym_open - spy_open) * side if sym_open is not None and spy_open is not None else None
            if kind == "opening_breakout":
                rel = rs_open
            else:
                sym_20 = (market_context or {}).get("return_20m")
                spy_20 = spy_context.get("return_20m")
                rs_20 = (sym_20 - spy_20) * side if sym_20 is not None and spy_20 is not None else None
                rel_candidates = [x for x in (rs_20, rs_open) if x is not None]
                rel = max(rel_candidates) if rel_candidates else None
            if rel is None:
                return "缺少相对SPY强弱基准数据，暂不进场"
            if rel < cfg.min_relative_strength and not math.isclose(rel, cfg.min_relative_strength, rel_tol=1e-10):
                return f"相对SPY强弱不足{cfg.min_relative_strength * 100:.2f}%，过滤弱势突破"

    if needs_leader and cfg.pool_leader_top_k > 0 and has_pool_rank:
        if not pool_rank or pool_rank.get("as_of") is None:
            return "缺少观察池横向强弱排名数据，暂不进场"
        if result.get("as_of") and abs((dt(result["as_of"]) - dt(pool_rank["as_of"])).total_seconds()) > 120:
            return "观察池横向强弱排名未对齐，暂不进场"
        rank = pool_rank.get("long_rank" if side == 1 else "short_rank")
        if rank is None:
            return "缺少观察池横向强弱排名数据，暂不进场"
        if rank > cfg.pool_leader_top_k:
            return f"横向强弱排名第{rank}位（需前{cfg.pool_leader_top_k}龙头），过滤非主浪标的"

    if needs_leader and (cfg.min_spy_open_move > 0 or cfg.min_pool_breadth > 0) and (has_spy_context or has_pool_rank):
        spy_aligned = bool(
            spy_context
            and spy_context.get("as_of") is not None
            and (
                not result.get("as_of")
                or abs((dt(result["as_of"]) - dt(spy_context["as_of"])).total_seconds()) <= 120
            )
        )
        if spy_open_dir is None and spy_aligned and spy_context.get("open_return") is not None:
            spy_open_dir = spy_context["open_return"] * side
        pool_aligned = bool(
            pool_rank
            and pool_rank.get("as_of") is not None
            and (
                not result.get("as_of")
                or abs((dt(result["as_of"]) - dt(pool_rank["as_of"])).total_seconds()) <= 120
            )
        )
        breadth = pool_rank.get("breadth_up" if side == 1 else "breadth_down") if pool_aligned else None
        spy_ok = (
            cfg.min_spy_open_move > 0
            and spy_aligned
            and spy_open_dir is not None
            and (
                spy_open_dir >= cfg.min_spy_open_move
                or math.isclose(spy_open_dir, cfg.min_spy_open_move, rel_tol=1e-10)
            )
        )
        breadth_ok = (
            cfg.min_pool_breadth > 0
            and breadth is not None
            and (breadth >= cfg.min_pool_breadth or math.isclose(breadth, cfg.min_pool_breadth, rel_tol=1e-10))
        )
        if not (spy_ok or breadth_ok):
            parts = []
            if cfg.min_spy_open_move > 0:
                parts.append(f"SPY顺向≥{cfg.min_spy_open_move * 100:.2f}%")
            if cfg.min_pool_breadth > 0:
                parts.append(f"全池广度≥{cfg.min_pool_breadth * 100:.0f}%")
            return f"大盘共振不足（需{'或'.join(parts)}）"
    return None


def plan(branch, result, price, now, quote_time=None, previous_plan=None, settings=None):
    cfg = settings or policy()
    side = 1 if branch["direction"] == "bullish" else -1
    kind = branch["kind"]
    rule = RULES[kind]
    interval = entry_interval(branch)
    needs_vwap = cfg.require_vwap and kind in ("opening_breakout", "midday_wave_breakout", "box_breakout")
    needs_spy = (
        (cfg.require_spy_alignment or cfg.min_spy_open_move > 0)
        and kind in ("opening_breakout", "midday_wave_breakout")
    )
    needs_open_move = (
        (cfg.min_open_move > 0 or (kind == "opening_breakout" and cfg.opening_min_efficiency > 0))
        and kind in ("opening_breakout", "midday_wave_breakout")
    )
    needs_pool_rank = (
        (cfg.pool_leader_top_k > 0 or cfg.min_pool_breadth > 0)
        and kind in ("opening_breakout", "midday_wave_breakout")
    )
    quote_floor = entry_quote_floor(branch, previous_plan, result.get("as_of"))
    if quote_floor and cfg.use_pivot_target and result.get("target_evidence_at"):
        quote_floor = max(quote_floor, dt(result["target_evidence_at"]))
    market_context = result.get("market_context")
    needs_gap = kind == "opening_breakout" and cfg.min_gap_directional is not None
    needs_market = needs_vwap or needs_spy or needs_open_move or needs_gap
    if quote_floor and needs_market and market_context and market_context.get("evidence_at"):
        quote_floor = max(quote_floor, dt(market_context["evidence_at"]))
    spy_context = result.get("spy_context")
    if quote_floor and needs_spy and spy_context and spy_context.get("evidence_at"):
        quote_floor = max(quote_floor, dt(spy_context["evidence_at"]))
    pool_rank = result.get("pool_rank_context")
    if quote_floor and needs_pool_rank and pool_rank and pool_rank.get("evidence_at"):
        quote_floor = max(quote_floor, dt(pool_rank["evidence_at"]))

    previous_plan = previous_plan or {}
    use_atr_ratchet = (
        not cfg.use_pivot_target
        and kind in START_KINDS
        and cfg.atr_scaled_exits
        and cfg.stop_loss_atr_mult > 0
    )
    fixed_wave = (
        not cfg.use_pivot_target
        and not use_atr_ratchet
        and kind in START_KINDS
        and (cfg.stop_loss_pct > 0 or cfg.take_profit_pct > 0)
    )
    atr_levels = (
        resolve_atr_exit_levels((result.get("daily_context") or {}).get("daily_atr_pct"), cfg)
        if use_atr_ratchet
        else None
    )
    if use_atr_ratchet and atr_levels is not None and price is not None:
        exec_invalidation = price * (1.0 - side * atr_levels["stop_loss_pct"])
    elif fixed_wave and cfg.stop_loss_pct > 0 and price is not None:
        exec_invalidation = price * (1.0 - side * cfg.stop_loss_pct)
    else:
        exec_invalidation = branch.get("invalidation")
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
    elif use_atr_ratchet and atr_levels is not None:
        if atr_levels["take_profit_pct"] > 0:
            target = price * (1.0 + side * atr_levels["take_profit_pct"]) if price is not None else None
            source = f"V8 ATR止盈(+{atr_levels['take_profit_pct'] * 100:.1f}%)"
        else:
            target = None
            source = "两档ATR棘轮锁盈·尾盘清仓"
        locked, lock_source, exhausted, required = None, None, False, False
    elif fixed_wave and cfg.take_profit_pct > 0:
        target = price * (1.0 + side * cfg.take_profit_pct) if price is not None else None
        source = f"V7波段止盈(+{cfg.take_profit_pct * 100:.1f}%)"
        locked, lock_source, exhausted, required = None, None, False, False
    else:
        target, source = None, "移动止损跟踪"
        locked, lock_source, exhausted, required = None, None, False, False

    economics = target_space(price, exec_invalidation, target, side, required, cfg)
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
    elif not (
        (interval[0] < price <= interval[1] if side == 1 else interval[0] <= price < interval[1])
        if rule.confirm_atr == 0
        else interval[0] <= price <= interval[1]
    ):
        reason = "形态已确认，当前报价不在冻结执行区间（不补记触发价成交）"
    elif rule.max_risk_atr is not None and (price - exec_invalidation) * side > rule.max_risk_atr * branch["atr"]:
        reason = f"当前报价到结构失效位超过{rule.max_risk_atr:g} ATR，风险距离过大"
    elif (
        cfg.minimum_risk_return > 0
        and economics["initial_risk_return"] is not None
        and economics["initial_risk_return"] < cfg.minimum_risk_return
        and not math.isclose(economics["initial_risk_return"], cfg.minimum_risk_return, rel_tol=1e-10)
    ):
        reason = f"初始风险幅度不足{cfg.minimum_risk_return * 100:.2f}%，过滤低波动噪音"
    elif (
        cfg.maximum_risk_return > 0
        and economics["initial_risk_return"] is not None
        and economics["initial_risk_return"] > cfg.maximum_risk_return
        and not math.isclose(economics["initial_risk_return"], cfg.maximum_risk_return, rel_tol=1e-10)
    ):
        reason = f"初始风险幅度超过{cfg.maximum_risk_return * 100:.2f}%，控制单笔止损上限"
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
    extra_exit = (
        {
            "exit_policy": "v8_atr_ratchet",
            "daily_atr_pct": atr_levels["daily_atr_pct"],
            "daily_atr_source": atr_levels["daily_atr_source"],
            "stop_loss_pct": atr_levels["stop_loss_pct"],
            "take_profit_pct": atr_levels["take_profit_pct"],
            "ratchet_tier1_trigger_pct": atr_levels["ratchet_tier1_trigger_pct"],
            "ratchet_tier1_lock_pct": atr_levels["ratchet_tier1_lock_pct"],
            "ratchet_tier2_trigger_pct": atr_levels["ratchet_tier2_trigger_pct"],
            "ratchet_tier2_lock_pct": atr_levels["ratchet_tier2_lock_pct"],
        }
        if use_atr_ratchet and atr_levels is not None
        else {}
    )
    return {
        **deepcopy(branch),
        "process_id": branch.get("process_id", branch["structure_id"]),
        "invalidation": exec_invalidation,
        "structure_invalidation": branch.get("invalidation"),
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
        **extra_exit,
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
    cfg = settings or policy()
    state = deepcopy(previous or {})
    previous_calculation = dt(state.get("calculated_at"))
    previous_healthy = state.get("healthy", False)
    events = []
    day = market_trading_date(now, "US")
    bounds = session_bounds("US", day)
    entry_cutoff = (
        min(
            bounds[0] + timedelta(minutes=cfg.entry_window_minutes),
            bounds[1] - timedelta(minutes=CONFIG.min_entry_before_close_minutes),
        )
        if bounds
        else None
    )
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
    monitor_quotes = phase == "active" or (
        phase == "stopped" and position is not None and now < dt(position["cutoff"])
    )
    state["data_issue"] = quote_issue(quote, now) if monitor_quotes else None
    monitor_data(state, monitor_quotes, state["data_issue"], quote, now, event)
    state["healthy"] = healthy
    if position:
        side = position["side"]
        due = now >= dt(position["cutoff"])
        # Never substitute next-day, out-of-order, or post-cutoff quotes for a missed planned exit.
        usable = price is not None and dt(position["last_price_at"]) <= quote.event_time <= dt(position["cutoff"])
        if usable:
            position.update(last_price=price, last_price_at=quote.event_time.isoformat())
        exit_price = position["last_price"] if due else price
        reason = None
        if due:
            reason = "当日收盘前清仓"
        elif usable:
            risk = abs(position["entry_price"] - position["invalidation"])
            gain = side * (price - position["entry_price"])
            position["peak_gain"] = max(position["peak_gain"], gain)
            if position.get("exit_policy") == "v8_atr_ratchet":
                if side * (price - position["protection"]) <= 0:
                    stage = position.get("protection_stage")
                    if stage == "ratchet_tier2":
                        reason = "二档棘轮锁盈触及"
                    elif stage == "ratchet_tier1":
                        reason = "一档保本锁盈触及"
                    else:
                        reason = "ATR止损触及"
                elif position["target"] is not None and side * (price - position["target"]) >= 0:
                    reason = "到达波段止盈目标"
                elif position["entry_price"] > 0:
                    peak_pct = position["peak_gain"] / position["entry_price"]
                    t1_trig = float(position.get("ratchet_tier1_trigger_pct") or 0.0)
                    t1_lock = float(position.get("ratchet_tier1_lock_pct") or 0.0)
                    t2_trig = float(position.get("ratchet_tier2_trigger_pct") or 0.0)
                    t2_lock = float(position.get("ratchet_tier2_lock_pct") or 0.0)
                    promoted_stage = None
                    promoted_trig = 0.0
                    promoted_lock = 0.0
                    if t2_trig > 0 and (peak_pct >= t2_trig or math.isclose(peak_pct, t2_trig, rel_tol=1e-10)):
                        promoted_stage, promoted_trig, promoted_lock = "ratchet_tier2", t2_trig, t2_lock
                    elif t1_trig > 0 and (peak_pct >= t1_trig or math.isclose(peak_pct, t1_trig, rel_tol=1e-10)):
                        promoted_stage, promoted_trig, promoted_lock = "ratchet_tier1", t1_trig, t1_lock
                    if promoted_stage is not None:
                        candidate = position["entry_price"] * (1.0 + side * promoted_lock)
                        if side * (candidate - position["protection"]) > 0:
                            position["protection"] = candidate
                            if position.get("protection_stage") != promoted_stage:
                                position["protection_active"] = True
                                position["protection_stage"] = promoted_stage
                                tier_label = "二档" if promoted_stage == "ratchet_tier2" else "一档"
                                lock_label = (
                                    "成本价保本" if promoted_lock == 0 else f"+{promoted_lock * 100:.2f}%锁盈"
                                )
                                event(
                                    "hold",
                                    f"浮盈已达+{promoted_trig * 100:.2f}%，{tier_label}棘轮保护位上移至{lock_label}",
                                    trade_id=position["id"],
                                    side=side,
                                )
                        if side * (price - position["protection"]) <= 0:
                            reason = (
                                "二档棘轮锁盈触及"
                                if position.get("protection_stage") == "ratchet_tier2"
                                else "一档保本锁盈触及"
                            )
            elif position.get("exit_policy") == "v7_fixed_wave":
                if side * (price - position["protection"]) <= 0:
                    reason = "保本锁盈保护触及" if position.get("protection_active") else "宏观止损触及"
                elif position["target"] is not None and side * (price - position["target"]) >= 0:
                    reason = "到达波段止盈目标"
                else:
                    trigger_pct = float(position.get("profit_lock_trigger_pct") or 0.0)
                    lock_pct = float(position.get("profit_lock_level_pct") or 0.0)
                    if trigger_pct > 0 and position["entry_price"] > 0:
                        peak_pct = position["peak_gain"] / position["entry_price"]
                        if peak_pct >= trigger_pct or math.isclose(peak_pct, trigger_pct, rel_tol=1e-10):
                            candidate = position["entry_price"] * (1.0 + side * lock_pct)
                            if side * (candidate - position["protection"]) > 0:
                                position["protection"] = candidate
                                if not position.get("protection_active"):
                                    position["protection_active"] = True
                                    position["protection_stage"] = "profit_lock"
                                    lock_label = "成本价保本" if lock_pct == 0 else f"+{lock_pct * 100:.2f}%锁盈"
                                    event(
                                        "hold",
                                        f"浮盈已达{trigger_pct * 100:.1f}%，保护位上移至{lock_label}",
                                        trade_id=position["id"],
                                        side=side,
                                    )
                        if side * (price - position["protection"]) <= 0:
                            reason = "保本锁盈保护触及"
            else:
                if side * (price - position["protection"]) <= 0:
                    reason = "移动止损或保护位触及" if position.get("protection_active") else "结构失效或保护位触及"
                elif position["target"] is not None and side * (price - position["target"]) >= 0:
                    reason = "到达目标"
                elif (
                    now - dt(position["entry_at"]) >= timedelta(minutes=CONFIG.no_progress_minutes)
                    and (gain <= 0 if CONFIG.no_progress_underwater_only else gain < risk * CONFIG.minimum_progress_r)
                ):
                    reason = (
                        f"{CONFIG.no_progress_minutes}分钟水下滞涨退出"
                        if CONFIG.no_progress_underwater_only
                        else "持有超时且未有效推进"
                    )
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
                    # A revised or excluded bar can tighten the structure stop after the latest quote.
                    evidence = (result or {}).get("target_evidence_at") if stage == "trailing" else None
                    observed_stop = evidence is None or quote.event_time >= dt(evidence)
                    if candidate is not None and observed_stop and side * (candidate - position["protection"]) > 0:
                        position["protection"] = candidate
                        if stage == "trailing" and position.get("protection_stage") != "trailing":
                            position["protection_active"] = True
                            position["protection_stage"] = "trailing"
                            event(
                                "hold",
                                f"浮盈已达{CONFIG.trail_after_r:g}R，启动{CONFIG.trail_bars}分钟结构移动止损",
                                trade_id=position["id"],
                                side=side,
                            )
                        elif stage == "breakeven" and not position.get("protection_active"):
                            position["protection_active"] = True
                            position["protection_stage"] = "breakeven"
                            event(
                                "hold",
                                f"浮盈已达{CONFIG.breakeven_after_r:g}R，保护位上移至成本价",
                                trade_id=position["id"],
                                side=side,
                            )
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
        if identity in frozen_levels:
            original = frozen_levels[identity]
            current = opportunities.get("start_levels", {}).get(identity, {})
            if any(original.get(k) != current.get(k) for k in ("atr", "width", "trigger")):
                item.update(executable=False, execution_reason="历史修订改变已冻结结构，等待独立新机会")
            elif original.setdefault("first_break", item["started_at"]) != item["started_at"]:
                item.update(executable=False, execution_reason="历史修订改变首次突破时刻，原过程不延长")
        elif item.get("opening_drive"):
            side_dir = 1 if item["direction"] == "bullish" else -1
            range_key = f"opening_range:{side_dir}:{item.get('formation_start')}"
            if range_key in frozen_levels:
                original = frozen_levels[range_key]
                current = opportunities.get("start_levels", {}).get(range_key, {})
                if any(original.get(k) != current.get(k) for k in ("atr", "width", "trigger")):
                    item.update(executable=False, execution_reason="历史修订改变已冻结结构，等待独立新机会")
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
            already_confirmed_process = bool(
                item.get("opening_drive")
                and any(v.get("process_id") == item["process_id"] for v in evidence.values())
            )
            evidence[item["structure_id"]] = deepcopy(item)
            if not already_confirmed_process:
                event("confirmed", "首次观察到形态确认", evidence=deepcopy(item))
    used = state.setdefault("used_processes", [])
    windows = state.setdefault("consumed_windows", [])
    # V4 persisted one consumed process per fill but had no daily counter.
    daily_entries = int(state.setdefault("daily_entry_count", len(used)) or 0)
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
            if chosen.get("exit_policy") == "v8_atr_ratchet":
                position.update(
                    exit_policy="v8_atr_ratchet",
                    protection_stage="initial",
                    daily_atr_pct=chosen["daily_atr_pct"],
                    daily_atr_source=chosen["daily_atr_source"],
                    stop_loss_pct=chosen["stop_loss_pct"],
                    take_profit_pct=chosen["take_profit_pct"],
                    ratchet_tier1_trigger_pct=chosen["ratchet_tier1_trigger_pct"],
                    ratchet_tier1_lock_pct=chosen["ratchet_tier1_lock_pct"],
                    ratchet_tier2_trigger_pct=chosen["ratchet_tier2_trigger_pct"],
                    ratchet_tier2_lock_pct=chosen["ratchet_tier2_lock_pct"],
                )
            elif not cfg.use_pivot_target and chosen["kind"] in START_KINDS and (
                cfg.stop_loss_pct > 0 or cfg.take_profit_pct > 0
            ):
                position.update(
                    exit_policy="v7_fixed_wave",
                    stop_loss_pct=cfg.stop_loss_pct,
                    take_profit_pct=cfg.take_profit_pct,
                    profit_lock_trigger_pct=cfg.profit_lock_trigger_pct,
                    profit_lock_level_pct=cfg.profit_lock_level_pct,
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
