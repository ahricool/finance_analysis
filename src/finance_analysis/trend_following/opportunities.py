"""Causal OHLCV opportunity records. Pattern owner: Trend10; Entry backgrounds: 10/20/40, independent of Alpha.

Prices are re-anchored from the same historical bar before every transition. JSON
records live in the existing atomic formal/preview snapshots; GET never detects.
"""

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from statistics import mean

from .features import calculate_atr
from .box import calculate_box_structure
from .config import DEFAULT_CONFIG

VERSION = "ohlcv_opportunity_v1"
BRANCHES = ("breakout", "ma5", "ma10", "retest", "flat_base", "box", "vcp", "cup_handle", "box_retest")
EVENT_STRATEGIES = {f"OP_{kind.upper()}_V1": kind for kind in BRANCHES}
EVENT_STRATEGIES["OP_STOCK_V1"] = "stock"


@dataclass(frozen=True)
class OpportunityConfig:
    history: int = 180
    advance_window: int = 20
    advance_min: float = 0.10
    minimum_turnover_proxy: float = 10000.0
    flat_windows: tuple = (25, 35)
    box_windows: tuple = (20, 40, 60)
    vcp_window: int = 80
    cup_window: int = 100
    pivot_right: int = 2
    pivot_noise: float = 0.025
    contraction_ratio: float = 0.85
    terminal_width: float = 0.08
    volume_dry: float = 0.85
    breakout_volume: float = 1.2
    min_atr: float = 0.1
    max_atr: float = 2.0
    max_extension: float = 0.05
    clv_min: float = 0.6
    flat_depth_min: float = 0.02
    flat_depth_max: float = 0.12
    flat_slope_max: float = 0.035
    flat_tightness_max: float = 0.10
    cup_depth_min: float = 0.12
    cup_depth_max: float = 0.35
    handle_depth_max: float = 0.12
    tracking_sessions: int = 30
    candidate_limit: int = 40


CONFIG = OpportunityConfig()


def select_primary(branches):
    """Quality never supplies state. All fields come from one confirmed record."""
    valid = [b for b in branches if b.get("status") == "CONFIRMED"]
    return min(valid, key=lambda b: (-(b.get("quality_score") or 0), b["kind"], b["structure_id"])) if valid else None


def order_key(item):
    b = item.get("primary") or item.get("display") or {}
    priority = {
        "CONFIRMED": 0,
        "NEAR_TRIGGER": 1,
        "PULLING_BACK": 2,
        "FORMING": 3,
        "WAITING_PULLBACK": 4,
        "EXTENDED": 5,
        "INVALIDATED": 6,
    }
    return priority.get(b.get("status"), 7), -(b.get("quality_score") or 0), item.get("code", "")


def confirmed_pivots(bars, right=2):
    """Each point carries both occurrence and first knowable date; never backdate."""
    points = []
    for i in range(right, len(bars) - right):
        window = bars[i - right : i + right + 1]
        for kind, value, extreme in (
            ("high", bars[i].high, max(b.high for b in window)),
            ("low", bars[i].low, min(b.low for b in window)),
        ):
            if value == extreme and sum(getattr(b, kind) == value for b in window) == 1:
                points.append(
                    dict(
                        kind=kind,
                        date=bars[i].trade_date.isoformat(),
                        price=value,
                        known_date=bars[i + right].trade_date.isoformat(),
                        index=i,
                    )
                )
    return points


def _advance(bars, start, config):
    if start < config.advance_window:
        return False
    prior = bars[start - config.advance_window : start]
    return prior[-1].close / prior[0].close - 1 >= config.advance_min


def detect_patterns(bars, config=CONFIG):
    """Candidates use T-1 only. Returned boundaries cannot contain the breakout bar."""
    prior = bars[:-1]
    found = []

    def add(kind, segment, trigger, support, quality, evidence, points=()):
        start = prior.index(segment[0])
        if not _advance(prior, start, config):
            return
        found.append(
            dict(
                kind=kind,
                start_date=segment[0].trade_date.isoformat(),
                end_date=segment[-1].trade_date.isoformat(),
                trigger=trigger,
                support=support,
                invalidation=support,
                quality_score=round(quality, 2),
                evidence=evidence,
                points=list(points),
            )
        )
        return True

    for kind, windows, depth_limit in (("flat_base", config.flat_windows, config.flat_depth_max),):
        for size in windows:
            if len(prior) < size + config.advance_window:
                continue
            w = prior[-size:]
            high, low = max(b.high for b in w), min(b.low for b in w)
            depth = (high - low) / high
            slope = abs(mean(b.close for b in w[-5:]) - mean(b.close for b in w[:5])) / high
            tightness = (max(b.close for b in w) - min(b.close for b in w)) / high
            upper = sum(
                b.high >= high - (high - low) * 0.15 and (i == 0 or w[i - 1].high < high - (high - low) * 0.15)
                for i, b in enumerate(w)
            )
            lower = sum(
                b.low <= low + (high - low) * 0.15 and (i == 0 or w[i - 1].low > low + (high - low) * 0.15)
                for i, b in enumerate(w)
            )
            volume = [b.volume for b in w if b.volume and b.volume > 0]
            dry = mean(volume[-5:]) / mean(volume[:-5]) if len(volume) == size and mean(volume[:-5]) else None
            if (
                config.flat_depth_min <= depth <= depth_limit
                and slope <= config.flat_slope_max
                and tightness <= config.flat_tightness_max
                and upper >= 2
                and lower >= 2
            ):
                accepted = add(
                    kind,
                    w,
                    high,
                    low,
                    60
                    + 20 * (1 - depth / depth_limit)
                    + 10 * (1 - slope / config.flat_slope_max)
                    + 10 * min(1, upper / 3),
                    dict(
                        depth=depth,
                        slope=slope,
                        tightness=tightness,
                        upper_touches=upper,
                        lower_touches=lower,
                        volume_dry_ratio=dry,
                        window=size,
                    ),
                )
                if accepted:
                    break
    # Reuse the existing width/flatness/occupancy/compression/touch quality, with
    # independent windows and a separately versioned frozen-boundary lifecycle.
    box_config = deepcopy(DEFAULT_CONFIG)
    eligible_box_windows = tuple(
        size
        for size in config.box_windows
        if len(prior) >= size + config.advance_window and _advance(prior, len(prior) - size, config)
    )
    object.__setattr__(box_config, "box_windows", eligible_box_windows)
    object.__setattr__(box_config, "box_min_days", min(config.box_windows))
    atr = calculate_atr(prior, 20)
    if eligible_box_windows and atr > 0:
        recent_atr = calculate_atr(prior, 5)
        earlier_atr = calculate_atr(prior[:-5], 20)
        recent_range = max(b.high for b in prior[-10:]) - min(b.low for b in prior[-10:])
        earlier_range = max(b.high for b in prior[-20:]) - min(b.low for b in prior[-20:])
        box = calculate_box_structure(
            bars,
            atr,
            {
                "atr_contraction_ratio": recent_atr / earlier_atr if earlier_atr else None,
                "range_contraction_ratio": recent_range / earlier_range if earlier_range else None,
            },
            box_config,
        )
        size = box.get("box_window_days")
        if (
            size
            and box.get("box_quality", 0) >= box_config.box_ready_quality_min
            and box.get("box_upper_touches", 0) >= 2
            and box.get("box_lower_touches", 0) >= 2
            and box.get("box_slope_atr", 99) <= 1.5
        ):
            add("box", prior[-size:], box["box_high"], box["box_low"], box["box_quality"], box)
    if len(prior) >= config.vcp_window + config.advance_window:
        w = prior[-config.vcp_window :]
        points = confirmed_pivots(w, config.pivot_right)
        swings = []
        peak = None
        for p in points:
            if p["kind"] == "high":
                if peak is None or p["price"] > peak["price"]:
                    peak = p
            elif peak and p["index"] > peak["index"]:
                depth = 1 - p["price"] / peak["price"]
                if depth >= config.pivot_noise:
                    segment = w[peak["index"] : p["index"] + 1]
                    volume = (
                        mean(b.volume for b in segment) if all(b.volume and b.volume > 0 for b in segment) else None
                    )
                    swings.append(dict(peak=peak, trough=p, depth=depth, volume=volume))
                    peak = None
        contractions = swings[-3:]
        if len(contractions) >= 2:
            first, final = contractions[0], contractions[-1]
            ratios = [b["depth"] / a["depth"] for a, b in zip(contractions, contractions[1:])]
            tail = w[final["trough"]["index"] :]
            width = max(b.high for b in tail) / min(b.low for b in tail) - 1
            volumes = [s["volume"] for s in contractions]
            dry = volumes[-1] / volumes[0] if all(v and v > 0 for v in volumes) else None
            if (
                all(r <= 1.05 for r in ratios)
                and final["depth"] <= first["depth"] * config.contraction_ratio
                and width <= config.terminal_width
                and len(tail) >= 3
            ):
                add(
                    "vcp",
                    w[first["peak"]["index"] :],
                    max(b.high for b in tail),
                    final["trough"]["price"],
                    70 + 20 * (1 - final["depth"] / first["depth"]) + 10 * (1 - width / config.terminal_width),
                    dict(
                        contractions=contractions, contraction_ratios=ratios, terminal_width=width, volume_dry_ratio=dry
                    ),
                    [p for s in contractions for p in (s["peak"], s["trough"])],
                )
    if len(prior) >= config.cup_window + config.advance_window:
        w = prior[-config.cup_window :]
        # Left rim in the first third; at least 20 bars on either side of the bottom.
        left = max(range(0, 30), key=lambda i: w[i].high)
        bottom = min(range(left + 20, len(w) - 20), key=lambda i: w[i].low)
        right = max(range(bottom + 15, len(w) - 5), key=lambda i: w[i].high)
        handle = w[right + 1 :]
        depth = 1 - w[bottom].low / w[left].high
        handle_depth = 1 - min(b.low for b in handle) / w[right].high
        near_bottom = sum(b.low <= w[bottom].low * 1.05 for b in w[left : right + 1])
        recovery = w[right].high / w[left].high
        if (
            config.cup_depth_min <= depth <= config.cup_depth_max
            and 0.90 <= recovery <= 1.05
            and 5 <= len(handle) <= 20
            and 0.01 <= handle_depth <= min(config.handle_depth_max, depth * 0.5)
            and min(b.low for b in handle) > (w[left].high + w[bottom].low) / 2
            and near_bottom >= 5
        ):
            dry = (
                mean(b.volume for b in handle) / mean(b.volume for b in w[left : right + 1])
                if all(b.volume and b.volume > 0 for b in w[left:])
                else None
            )
            points = [
                dict(date=w[i].trade_date.isoformat(), price=value, known_date=w[-1].trade_date.isoformat())
                for i, value in (
                    (left, w[left].high),
                    (bottom, w[bottom].low),
                    (right, w[right].high),
                    (right + 1 + min(range(len(handle)), key=lambda i: handle[i].low), min(b.low for b in handle)),
                )
            ]
            add(
                "cup_handle",
                w[left:],
                max(b.high for b in handle),
                min(b.low for b in handle),
                75 + 15 * (1 - handle_depth / depth) + 10 * min(1, near_bottom / 10),
                dict(
                    cup_depth=depth,
                    handle_depth=handle_depth,
                    recovery=recovery,
                    bottom_sessions=near_bottom,
                    volume_dry_ratio=dry,
                ),
                points,
            )
    return found


def _price_scale(record, bars):
    anchor = next((b for b in bars if b.trade_date.isoformat() == record.get("anchor_date")), None)
    return anchor.close / record["anchor_close"] if anchor and record.get("anchor_close") else None


def build_opportunities(
    code, bars, entry, previous=None, *, preview=False, sessions=None, config=CONFIG, trend_period=10
):
    ordered = sorted(bars, key=lambda b: b.trade_date)[-config.history :]
    result = dict(
        version=VERSION,
        branches=[],
        primary=None,
        display=None,
        events=[],
        history_status="insufficient",
        preview=preview,
        code=code,
        background_periods=[trend_period],
    )
    if len(ordered) < 22:
        return result
    result["branch_history_ready"] = {
        **{
            kind: bool(entry.get("entry_context", {}).get("history_ready"))
            for kind in ("breakout", "ma5", "ma10", "retest")
        },
        "flat_base": len(ordered) >= min(config.flat_windows) + config.advance_window + 1 and trend_period == 10,
        "box": len(ordered) >= min(config.box_windows) + config.advance_window + 1 and trend_period == 10,
        "box_retest": len(ordered) >= min(config.box_windows) + config.advance_window + 1 and trend_period == 10,
        "vcp": len(ordered) >= config.vcp_window + config.advance_window + 1 and trend_period == 10,
        "cup_handle": len(ordered) >= config.cup_window + config.advance_window + 1 and trend_period == 10,
    }
    day = ordered[-1].trade_date.isoformat()
    result["data_as_of"] = day
    invalid = any(
        not all(isfinite(v) and v > 0 for v in (b.open, b.high, b.low, b.close))
        or b.low > min(b.open, b.close)
        or b.high < max(b.open, b.close)
        or b.low > b.high
        for b in ordered
    )
    dates = [b.trade_date for b in ordered]
    missing = sessions is not None and any(d not in dates for d in sessions if dates[0] <= d <= dates[-1])
    if invalid or missing or len(set(dates)) != len(dates):
        result["history_status"] = "invalid_ohlc" if invalid else "missing_sessions"
        return result
    result["history_status"] = (
        "complete" if len(ordered) >= config.cup_window + config.advance_window + 1 else "partial"
    )
    prior = (
        previous if previous and previous.get("version") == VERSION and previous.get("data_as_of", day) <= day else {}
    )
    old = {b["kind"]: b for b in prior.get("branches", [])}
    today = ordered[-1]
    atr = calculate_atr(ordered[:-1], 20)
    if atr <= 0:
        return result
    candidates = {b["kind"]: b for b in detect_patterns(ordered, config)} if trend_period == 10 else {}
    # Follow an already discovered boundary, never replace it with today's rolling window.
    for kind in ("flat_base", "box", "vcp", "cup_handle"):
        previous_branch = old.get(kind)
        if previous_branch and previous_branch["status"] != "INVALIDATED":
            elapsed = sum(b.trade_date.isoformat() > previous_branch["discovered_at"] for b in ordered)
            if elapsed <= config.tracking_sessions:
                record = deepcopy(previous_branch)
                scale = _price_scale(record, ordered)
                if scale is not None:
                    for field in ("trigger", "support", "invalidation"):
                        record[field] *= scale
                    for point in record.get("points", []):
                        point["price"] *= scale
                    candidates[kind] = record
    # An overlapping rolling window is not a new structure after expiry/failure.
    for kind in ("flat_base", "box", "vcp", "cup_handle"):
        previous_branch = old.get(kind)
        candidate = candidates.get(kind)
        if previous_branch and (not candidate or candidate.get("structure_id") != previous_branch["structure_id"]):
            if not candidate or candidate["start_date"] <= previous_branch["end_date"]:
                record = deepcopy(previous_branch)
                scale = _price_scale(record, ordered)
                if scale is not None:
                    for field in ("trigger", "support", "invalidation"):
                        record[field] *= scale
                    for point in record.get("points", []):
                        point["price"] *= scale
                record["status"] = "INVALIDATED"
                record["reason"] = "结构结束，等待独立的新形成区间"
                record["expired"] = True
                candidates[kind] = record
    records = []
    turnover = [
        (
            b.amount
            if b.amount is not None and b.amount > 0
            else b.close * b.volume if b.volume is not None and isfinite(b.volume) and b.volume > 0 else None
        )
        for b in ordered[-21:-1]
    ]
    liquidity_ready = all(v is not None and isfinite(v) for v in turnover)
    turnover_proxy = mean(turnover) if liquidity_ready else None
    liquid = turnover_proxy is not None and turnover_proxy >= config.minimum_turnover_proxy
    background_healthy = today.close >= mean(b.close for b in ordered[-20:]) and mean(
        b.close for b in ordered[-20:]
    ) >= mean(b.close for b in ordered[-21:-1])
    result["background"] = dict(
        trend_healthy=background_healthy,
        turnover_proxy=turnover_proxy,
        liquidity_ready=liquidity_ready,
        liquidity_pass=liquid,
    )
    volume_ready = all(b.volume is not None and b.volume > 0 for b in ordered[-21:])
    volume_ratio = today.volume / mean(b.volume for b in ordered[-21:-1]) if volume_ready else None
    for kind, record in candidates.items():
        record = deepcopy(record)
        record.setdefault("structure_id", f"{VERSION}:{code}:{kind}:{record['start_date']}:{record['end_date']}")
        record.setdefault("discovered_at", day)
        record.setdefault("first_confirmed_at", None)
        distance = (today.close - record["trigger"]) / atr
        pct = today.close / record["trigger"] - 1
        dry = record["evidence"].get("volume_dry_ratio")
        volume_pass = not preview and volume_ratio is not None and volume_ratio >= config.breakout_volume
        if kind in ("vcp", "cup_handle"):
            volume_pass = volume_pass and dry is not None and dry <= config.volume_dry
        unmet = []
        if not volume_pass:
            unmet.append("待收盘验证量能" if preview else "量能证据不足")
        clv = (today.close - today.low) / (today.high - today.low) if today.high > today.low else 0
        if clv < config.clv_min:
            unmet.append("收盘位置不足")
        if (
            record.get("expired")
            or today.close < record["invalidation"]
            or (record["first_confirmed_at"] and today.close < record["trigger"] - 0.5 * atr)
        ):
            status = "INVALIDATED"
        elif distance > config.max_atr or pct > config.max_extension:
            status = "EXTENDED"
        elif record["first_confirmed_at"] and distance >= 0:
            status = "CONFIRMED"
        elif distance >= config.min_atr and not unmet:
            status = "CONFIRMED"
        elif pct >= -0.03:
            status = "NEAR_TRIGGER"
        else:
            status = "FORMING"
        record.update(
            status=status,
            unmet=unmet,
            distance_atr=distance,
            distance_pct=pct,
            volume_ratio=volume_ratio,
            reason=(
                "结构结束或已跌破失效边界，等待新结构"
                if status == "INVALIDATED"
                else (
                    "距原触发位过远，已超出合理执行区间"
                    if status == "EXTENDED"
                    else (
                        "已正式确认且仍在原结构有效区间"
                        if status == "CONFIRMED"
                        else "；".join(unmet) or "等待收盘突破已知边界"
                    )
                )
            ),
        )
        records.append(record)
    box = next((r for r in records if r["kind"] == "box"), None)
    if box and box.get("first_confirmed_at") and box["first_confirmed_at"] < day:
        record = deepcopy(box)
        record.update(
            kind="box_retest",
            structure_id=box["structure_id"] + ":retest",
            trigger=box["trigger"],
            support=box["trigger"],
            invalidation=box["trigger"] - 0.75 * atr,
            first_confirmed_at=None,
            fresh=False,
        )
        prior_retest = old.get("box_retest", {})
        touch = prior_retest.get("touch_date") if prior_retest.get("structure_id") == record["structure_id"] else None
        touch = touch or (day if today.low <= box["trigger"] + 0.25 * atr else None)
        record["touch_date"] = touch
        if prior_retest.get("structure_id") == record["structure_id"]:
            record["first_confirmed_at"] = prior_retest.get("first_confirmed_at")
        if (
            box["status"] == "INVALIDATED"
            or today.low < record["invalidation"]
            or prior_retest.get("status") == "INVALIDATED"
        ):
            record["status"] = "INVALIDATED"
        elif record["distance_atr"] > config.max_atr or record["distance_pct"] > config.max_extension:
            record["status"] = "EXTENDED"
        elif touch and today.close >= record["trigger"] + 0.1 * atr and today.close > ordered[-2].close:
            record["status"] = "CONFIRMED"
        else:
            record["status"] = "PULLING_BACK" if touch else "WAITING_PULLBACK"
        record["reason"] = "原箱顶回测恢复；量能仅作背景，不宣称缩量确认"
        records.append(record)
    breakdown = entry.get("entry_breakdown", {})
    execution_atr = entry.get("entry_context", {}).get("atr") or atr
    failure_atr = breakdown.get("parameters", {}).get("entry_support_failure_atr", 0.75)
    for kind in ("breakout", "ma5", "ma10", "retest"):
        branch = breakdown.get("breakout", {}) if kind == "breakout" else breakdown.get("pullbacks", {}).get(kind, {})
        evidence = branch.get("evidence", {})
        support = evidence.get("support")
        if not support:
            continue
        start = evidence.get("touch_date") or evidence.get("breakout_date") or day
        structure_id = f"{VERSION}:{code}:{kind}:{start}"
        previous_branch = old.get(kind)
        # A continuous recovery remains one episode until invalidation or a new touch.
        if previous_branch and previous_branch["status"] != "INVALIDATED" and kind == "breakout":
            structure_id = previous_branch["structure_id"]
        record = dict(
            kind=kind,
            structure_id=structure_id,
            start_date=start,
            end_date=day,
            discovered_at=day,
            first_confirmed_at=None,
            status=branch.get("status", "WAITING_PULLBACK"),
            quality_score=branch.get("quality_score"),
            trigger=support,
            support=support,
            invalidation=support - failure_atr * execution_atr,
            distance_atr=(today.close - support) / execution_atr,
            distance_pct=today.close / support - 1,
            evidence=evidence,
            points=[],
            unmet=[k for k, v in branch.get("checks", {}).items() if not v],
            reason=branch.get("reason"),
        )
        if kind == "breakout" and previous_branch and previous_branch["structure_id"] == structure_id:
            scale = _price_scale(previous_branch, ordered)
            if scale:
                for field in ("trigger", "support", "invalidation"):
                    record[field] = previous_branch[field] * scale
                record["start_date"], record["end_date"] = previous_branch["start_date"], previous_branch["end_date"]
                record["distance_atr"] = (today.close - record["trigger"]) / execution_atr
                record["distance_pct"] = today.close / record["trigger"] - 1
                if today.close < record["invalidation"]:
                    record["status"] = "INVALIDATED"
                elif record["distance_atr"] > config.max_atr or record["distance_pct"] > config.max_extension:
                    record["status"] = "EXTENDED"
                elif previous_branch.get("first_confirmed_at") and today.close >= record["trigger"]:
                    record["status"] = "CONFIRMED"
        if previous_branch and previous_branch["structure_id"] == structure_id:
            record["discovered_at"] = previous_branch["discovered_at"]
            record["first_confirmed_at"] = previous_branch.get("first_confirmed_at")
        records.append(record)
    for record in records:
        if record.get("quality_score") is not None and not isfinite(record["quality_score"]):
            record["quality_score"] = None
        record.update(
            rule_version=VERSION,
            preview=preview,
            data_as_of=day,
            anchor_date=day,
            anchor_close=today.close,
            price_basis="forward_adjusted",
            background_periods=[trend_period],
        )
        if record["status"] == "CONFIRMED" and not liquid:
            record["status"] = "NEAR_TRIGGER"
            record["unmet"].append("基础流动性证据不足")
            record["reason"] = "价格条件满足，基础流动性证据不足，暂不作为有效机会"
        if (
            record["kind"] in ("flat_base", "box", "vcp", "cup_handle", "box_retest")
            and record["status"] == "CONFIRMED"
            and not background_healthy
        ):
            record["status"] = "INVALIDATED"
            record["reason"] = "当前20日均线结构已转弱"
        record["fresh"] = record["status"] == "CONFIRMED" and not record.get("first_confirmed_at") and not preview
        if record["fresh"]:
            record["first_confirmed_at"] = day
            result["events"].append(record["kind"])
        if record["status"] == "INVALIDATED":
            record.setdefault("invalidated_at", day)
    result["branches"] = records
    result["primary"] = select_primary(records)
    result["display"] = result["primary"] or min(records, key=lambda b: order_key({"display": b}), default=None)
    return result


def opportunity_items(rows):
    """Union periods by stock and structure; quality never creates independent votes."""
    grouped = {}
    for row in rows:
        document = (row.get("features") or {}).get("opportunities")
        if not document:
            continue
        code = row["code"]
        item = grouped.setdefault(code, dict(document, code=code, name=row.get("name") or code, branches=[]))
        for branch in document.get("branches", []):
            existing = next((b for b in item["branches"] if b["structure_id"] == branch["structure_id"]), None)
            if existing:
                periods = sorted(set(existing.get("background_periods", []) + branch.get("background_periods", [])))
                if order_key({"display": branch}) < order_key({"display": existing}):
                    existing.update(deepcopy(branch))
                existing["background_periods"] = periods
            else:
                item["branches"].append(deepcopy(branch))
    for item in grouped.values():
        item["primary"] = select_primary(item["branches"])
        item["display"] = item["primary"] or min(
            item["branches"], key=lambda b: order_key({"display": b}), default=None
        )
    return sorted(grouped.values(), key=order_key)
