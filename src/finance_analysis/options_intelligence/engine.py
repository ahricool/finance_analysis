"""Explainable three-score calculation and event candidates, without LLM decisions."""

from collections import defaultdict
from statistics import mean
from math import isfinite

from .metrics import (
    cohort,
    liquidity,
    percentile,
    realized_volatility,
    standard_iv,
    term_metrics,
    volume_oi,
    weighted_score,
    iv_usable,
)


def analyze(chain, session_date, now, history, mode, config, closes=(), oi_changes=None):
    oi_changes = oi_changes or {}
    rows = chain.observations
    groups = defaultdict(list)
    for row in rows:
        groups[(row.data_source, row.feed_type)].append(row)
    source_order = sorted(groups, key=lambda key: (key[0] != "yfinance", key[1] == "indicative"))

    def valid_volume(row):
        return row.volume_date == session_date and row.volume is not None and isfinite(row.volume) and row.volume >= 0

    # Select a complete source with usable 22–45D Put/Call observations before
    # allowing yesterday's Yahoo volumes to hide a usable fallback capability.
    primary = next(
        (
            groups[key]
            for key in source_order
            if all(
                any(
                    valid_volume(r) and r.option_type == kind and 22 <= (r.expiration - session_date).days <= 45
                    for r in groups[key]
                )
                for kind in ("call", "put")
            )
        ),
        None,
    )
    if primary is None:
        primary = next((groups[key] for key in source_order if any(valid_volume(r) for r in groups[key])), [])
    primary_ids = {id(r) for r in primary}
    # Volume/OI capability falls back per complete source observation, never by joining fields.
    activity_rows = {}
    for key in source_order:
        for row in groups[key]:
            if (
                row.symbol not in activity_rows
                and row.volume_date == session_date
                and volume_oi(row.volume, row.open_interest, config) is not None
            ):
                activity_rows[row.symbol] = row
    # A closed-session chain is the volume baseline. Intraday comparison uses the same clock bucket only.
    comparable = [h for h in history if h["trade_date"] < session_date and h["mode"] == mode]
    volatility_comparable = (
        comparable
        if mode == "daily"
        else [h for h in history if h["trade_date"] < session_date and h["mode"] == "daily"]
    )
    base_days = len({h["trade_date"] for h in volatility_comparable})
    baselines = defaultdict(list)
    for item in comparable:
        for old in item["rows"]:
            key = cohort(old, item["trade_date"])
            if key and old.volume is not None and old.volume_date == item["trade_date"]:
                baselines[key].append((item["trade_date"], old.volume))
    contracts, candidates = [], []
    source_metrics = {key: term_metrics(groups[key], session_date, now, config) for key in source_order}
    # Keep each provider's complete calculations intact; choose a whole row per actual expiry.
    expirations = sorted({t["expiration"] for items in source_metrics.values() for t in items})
    displayed = {}
    for expiry in expirations:
        choices = [t for key in source_order for t in source_metrics[key] if t["expiration"] == expiry]
        displayed[expiry] = next(
            (t for t in choices if t["atm_iv"] is not None),
            next((t for t in choices if t["expected_move"] is not None), choices[0]),
        )
    iv30_term = next((source_metrics[k] for k in source_order if standard_iv(source_metrics[k])[0] is not None), [])
    iv30, iv30_method = standard_iv(iv30_term)
    selected_source = (iv30_term[0]["source"], iv30_term[0]["feed_type"]) if iv30_term else None
    # If Yahoo lacks the *30D target*, display the coherent fallback bracket used by that target.
    # Do not hide one interpolation leg behind a Yahoo-only expiry with a different IV.
    iv30_references = []
    valid_iv30 = sorted((t for t in iv30_term if t["atm_iv"] is not None), key=lambda t: t["dte"])
    exact = next((t for t in valid_iv30 if t["dte"] == 30), None)
    if exact:
        iv30_references = [exact]
    else:
        for left, right in zip(valid_iv30, valid_iv30[1:]):
            if left["dte"] < 30 < right["dte"]:
                iv30_references = [left, right]
                break
    for item in iv30_references:
        displayed[item["expiration"]] = item
    term = [displayed[expiry] for expiry in expirations]
    iv_history = [
        h["metrics"].get("iv_30d")
        for h in volatility_comparable
        if h["metrics"].get("iv_source") == list(selected_source or ())
    ]
    iv_percentile = percentile(iv30, iv_history, config.min_history_days)
    target_skews = []
    for target in (7, 30, 60):
        item = None
        for key in source_order:
            choices = [
                t
                for t in source_metrics[key]
                if t["skew_25"] is not None and abs(t["dte"] - target) <= max(3, target * config.skew_tenor_tolerance)
            ]
            if choices:
                item = min(choices, key=lambda t: abs(t["dte"] - target))
                break
        target_skews.append(
            {
                "target_dte": target,
                "actual_dte": item["dte"] if item else None,
                "expiration": item["expiration"] if item else None,
                "value": item["skew_25"] if item else None,
                "source": item["source"] if item else None,
                "feed_type": item["feed_type"] if item else None,
                "reason": None if item else "valid_delta_bracket_unavailable",
            }
        )
    skew30 = target_skews[1]
    skew_history = [
        h["metrics"].get("skew_30d")
        for h in volatility_comparable
        if h["metrics"].get("skew_source") == [skew30["source"], skew30["feed_type"]]
    ]
    prior_skew = next(
        (
            h["metrics"].get("skew_30d")
            for h in reversed(volatility_comparable)
            if h["metrics"].get("skew_source") == [skew30["source"], skew30["feed_type"]]
            and h["metrics"].get("skew_terms", [{}, {}, {}])[1].get("expiration") == skew30["expiration"]
            and h["metrics"].get("skew_30d") is not None
        ),
        None,
    )
    skew_change = skew30["value"] - prior_skew if skew30["value"] is not None and prior_skew is not None else None
    ratios, ratio_coverage = [], []
    for low, high in ((1, 7), (8, 21), (22, 45), (46, config.max_dte)):

        def valid(r):
            return r.volume_date == session_date and r.volume is not None and isfinite(r.volume) and r.volume >= 0

        unique = {}
        raw = [r for r in primary if low <= (r.expiration - session_date).days <= high]
        for row in raw:
            identity = row.symbol, row.option_type, row.expiration, row.strike
            if identity not in unique or not valid(unique[identity]) and valid(row):
                unique[identity] = row
        subset = list(unique.values())
        put = [r for r in subset if r.option_type == "put"]
        call = [r for r in subset if r.option_type == "call"]

        def ratio(field):
            pv, cv = [getattr(r, field) for r in put], [getattr(r, field) for r in call]
            if not pv or not cv or any(v is None for v in pv + cv) or sum(cv) <= 0:
                return None
            return sum(pv) / sum(cv)

        # Only this source/feed's valid current-session observations contribute to volume.
        valid_put, valid_call = [r for r in put if valid(r)], [r for r in call if valid(r)]
        call_volume = sum(r.volume for r in valid_call)
        volume_ratio = sum(r.volume for r in valid_put) / call_volume if valid_put and call_volume > 0 else None
        complete = len(valid_put) == len(put) and len(valid_call) == len(call)
        ratio_coverage.append(
            {
                "dte_min": low,
                "dte_max": high,
                "source": primary[0].data_source if primary else None,
                "feed_type": primary[0].feed_type if primary else None,
                "put_contracts": len(put),
                "call_contracts": len(call),
                "duplicate_contracts_excluded": len(raw) - len(subset),
                "valid_put_contracts": len(valid_put),
                "valid_call_contracts": len(valid_call),
                "valid_put_volume": sum(r.volume for r in valid_put),
                "valid_call_volume": call_volume,
                "put_valid_fraction": len(valid_put) / len(put) if put else None,
                "call_valid_fraction": len(valid_call) / len(call) if call else None,
                "confidence": "low" if not complete or not valid_put or not call_volume else "filtered_chain_only",
            }
        )
        ratios.append(
            {
                "dte_min": low,
                "dte_max": high,
                "volume_ratio": volume_ratio,
                "oi_ratio": ratio("open_interest"),
                "source": primary[0].data_source if primary else None,
                "reason": (
                    "no_contracts"
                    if not subset
                    else (
                        "valid_current_volume_unavailable"
                        if volume_ratio is None
                        else "partial_valid_volume_subset" if not complete else "filtered_chain_observed_session"
                    )
                )
                + ("; OI_date_unknown" if any(r.oi_date is None for r in subset) else ""),
            }
        )
    pc30 = ratios[2]["volume_ratio"]
    pc_history = [
        h["metrics"].get("put_call_volume_ratio")
        for h in comparable
        if h["metrics"].get("volume_source") == (primary[0].data_source if primary else None)
        and h["metrics"].get("volume_feed") == (primary[0].feed_type if primary else None)
    ]
    put_iv, put_iv_source = None, None
    for key in source_order:
        put_iv_values = [
            r.iv
            for r in groups[key]
            if r.option_type == "put"
            and iv_usable(r, now, config)
            and r.underlying_price
            and 22 <= (r.expiration - session_date).days <= 45
            and config.put_iv_min_moneyness <= r.strike / r.underlying_price <= config.put_iv_max_moneyness
        ]
        if put_iv_values:
            put_iv, put_iv_source = mean(put_iv_values), list(key)
            break
    put_iv_history = [
        h["metrics"].get("put_iv") for h in volatility_comparable if h["metrics"].get("put_iv_source") == put_iv_source
    ]
    activity_percentiles, active_ratios = [], []
    liquidity_by_contract = {}
    directional_anomalies = defaultdict(set)
    estimated_put_premiums = []
    for row in rows:
        risk = liquidity(row, now, session_date, config)
        key = cohort(row, session_date)
        samples = baselines.get(key, [])
        days = len({day for day, _ in samples})
        volume_pct = (
            percentile(row.volume, [value for _, value in samples], 1)
            if days >= config.min_history_days and row.volume_date == session_date
            else None
        )
        ratio = volume_oi(row.volume, row.open_interest, config) if row.volume_date == session_date else None
        # A latest trade is not a daily VWAP. Even Last x Volume is an explicitly labelled estimate.
        premium = (
            row.volume * risk["mid"] * row.multiplier
            if (
                row.volume is not None
                and row.volume_date == session_date
                and risk["mid"] is not None
                and row.multiplier is not None
            )
            else None
        )
        actual_premium = (
            row.volume * row.traded_price * row.multiplier
            if (
                row.volume is not None
                and row.traded_price is not None
                and row.multiplier is not None
                and row.traded_price_method == "reported_daily_vwap"
                and row.feed_type == "opra"
                and row.volume_date == session_date
            )
            else None
        )
        oi = oi_changes.get((row.symbol, row.data_source, row.feed_type))
        detail = {
            **row.model_dump(mode="json"),
            **risk,
            "volume_percentile": volume_pct,
            "baseline_days": days,
            "premium_volume": actual_premium,
            "premium_estimate": premium,
            "premium_method": "mid_times_volume_estimate",
            "oi_change": oi,
            "events": [],
        }
        if risk["observed_risk"]["value"] is not None:
            priority = (
                risk["quote_status"] != "valid",
                risk["quote_status"] != "indicative_not_nbbo",
                row.data_source != "yfinance",
            )
            previous = liquidity_by_contract.get(row.symbol)
            if previous is None or priority < previous[0]:
                liquidity_by_contract[row.symbol] = (priority, risk["observed_risk"]["value"])
        if activity_rows.get(row.symbol) is row and ratio is not None:
            active_ratios.append(min(100, ratio / config.volume_oi_alert * config.activity_rule_level))
        if id(row) in primary_ids:
            if volume_pct is not None:
                activity_percentiles.append(volume_pct)
            if row.option_type == "put" and premium is not None:
                estimated_put_premiums.append(premium)

        def event(kind, value, reference, severity, explanation):
            detail["events"].append(kind)
            if (id(row) in primary_ids or activity_rows.get(row.symbol) is row) and kind in {
                "PUT_VOLUME_SPIKE",
                "CALL_VOLUME_SPIKE",
                "VOLUME_OI_ANOMALY",
            }:
                directional_anomalies[row.option_type].add(row.symbol)
            candidates.append(
                {
                    "contract_symbol": row.symbol,
                    "event_type": kind,
                    "value": value,
                    "reference": reference,
                    "severity": severity,
                    "source": row.data_source,
                    "feed_type": row.feed_type,
                    "data_time": (
                        row.quote_timestamp if kind in {"WIDE_BID_ASK_SPREAD", "LIQUIDITY_DRY_UP"} else row.observed_at
                    ).isoformat(),
                    "volume_date": row.volume_date.isoformat() if row.volume_date else None,
                    "oi_date": row.oi_date.isoformat() if row.oi_date else None,
                    "direction": (
                        "liquidity_risk"
                        if kind in {"WIDE_BID_ASK_SPREAD", "LIQUIDITY_DRY_UP"}
                        else (
                            "oi_structure"
                            if kind == "OI_BUILDUP_CONFIRMED"
                            else "put_demand" if row.option_type == "put" else "call_activity"
                        )
                    ),
                    "explanation": explanation,
                }
            )

        if volume_pct is not None and volume_pct >= config.percentile_alert and row.volume >= config.min_volume:
            event(
                "PUT_VOLUME_SPIKE" if row.option_type == "put" else "CALL_VOLUME_SPIKE",
                row.volume,
                {"percentile": volume_pct, "sample_days": days, "cohort": list(key)},
                volume_pct,
                "相同标的、类型、DTE、Moneyness、来源及采样时段的历史成交异常；无法判断开仓方向。",
            )
        if ratio is not None and ratio >= config.volume_oi_alert:
            event(
                "VOLUME_OI_ANOMALY",
                ratio,
                {"threshold": config.volume_oi_alert},
                min(100, ratio / config.volume_oi_alert * config.activity_rule_level),
                "满足最小成交量和OI；交易活跃度不代表净开仓。",
            )
        if premium is not None and premium >= config.premium_alert and id(row) in primary_ids:
            event(
                "LARGE_PREMIUM_ACTIVITY",
                premium,
                {"threshold": config.premium_alert, "estimated": True},
                75,
                "Mid × 当日Volume × multiplier估算，非实际成交权利金。",
            )
        if risk["quote_status"] == "valid" and risk["spread"] > config.wide_spread_factor * risk["spread_allowance"]:
            event(
                "WIDE_BID_ASK_SPREAD",
                risk["spread"],
                {"allowance": risk["spread_allowance"]},
                min(100, risk["spread"] / risk["spread_allowance"] * 25),
                "按权利金、DTE、价内外程度调整的初始点差规则。",
            )
        if risk["risk"]["value"] is not None and risk["risk"]["value"] >= config.liquidity_alert:
            event(
                "LIQUIDITY_DRY_UP",
                risk["risk"]["value"],
                {"rule": config.rule_version},
                risk["risk"]["value"],
                "有效新鲜报价下的宽点差、低成交/OI与可见最优报价深度证据。",
            )
        if (
            oi
            and oi["change"] >= config.oi_change_alert
            and oi["previous"] >= config.min_oi
            and (oi["change"] / oi["previous"] >= config.oi_growth_alert)
        ):
            event(
                "OI_BUILDUP_CONFIRMED",
                oi["change"],
                oi,
                75,
                "相邻有效交易日已发布OI增加；于known_at才可知，不代表新增净看空。",
            )
        contracts.append(detail)
    put_premium = sum(estimated_put_premiums) if estimated_put_premiums else None
    put_premium_history = [
        h["metrics"].get("put_premium_estimate")
        for h in comparable
        if h["metrics"].get("volume_source") == (primary[0].data_source if primary else None)
        and h["metrics"].get("volume_feed") == (primary[0].feed_type if primary else None)
    ]
    # Count contracts once even when multiple sources publish the same dated OI increase.
    oi_confirmed = {
        key[0]
        for key, value in oi_changes.items()
        if value["change"] >= config.oi_change_alert
        and value["previous"] >= config.min_oi
        and value["change"] / value["previous"] >= config.oi_growth_alert
    }
    put_oi_confirmed = oi_confirmed & {r.symbol for r in rows if r.option_type == "put"}
    # No historical baseline -> volume/OI is an explicitly provisional absolute-rule score only.
    activity = weighted_score(
        [
            max(activity_percentiles) if activity_percentiles else None,
            max(active_ratios) if active_ratios else None,
            percentile(put_premium, put_premium_history, config.min_history_days),
            min(100, len(oi_confirmed) * config.corroboration_increment) if oi_confirmed else None,
            (
                min(100, max(map(len, directional_anomalies.values())) * config.corroboration_increment)
                if directional_anomalies and max(map(len, directional_anomalies.values())) >= 2
                else None
            ),
        ],
        config.activity_weights,
        "historical_percentiles" if activity_percentiles else "initial_absolute_volume_oi_rules",
        "insufficient_history_and_absolute_activity_evidence",
    )
    pc_percentile = percentile(pc30, pc_history, config.min_history_days)
    skew_percentile = percentile(skew30["value"], skew_history, config.min_history_days)
    put_iv_percentile = percentile(put_iv, put_iv_history, config.min_history_days)
    pc_rule = (
        min(100, pc30 / config.put_call_demand_reference * 50)
        if pc30 is not None
        and ratio_coverage[2]["valid_put_volume"] + ratio_coverage[2]["valid_call_volume"] >= config.min_volume
        else None
    )
    skew_rule = (
        min(100, max(0, skew30["value"]) / config.skew_alert * config.activity_rule_level)
        if skew30["value"] is not None
        else None
    )
    bearish_values = [
        pc_percentile if pc_percentile is not None else pc_rule,
        put_iv_percentile,
        skew_percentile if skew_percentile is not None else skew_rule,
        (
            min(100, max(0, skew_change) / config.skew_change_alert * config.activity_rule_level)
            if skew_change is not None
            else None
        ),
        percentile(put_premium, put_premium_history, config.min_history_days),
        (min(100, len(put_oi_confirmed) * config.corroboration_increment) if put_oi_confirmed else None),
    ]
    bearish = weighted_score(
        bearish_values,
        config.bearish_weights,
        (
            "historical_percentiles"
            if any(v is not None for v in (pc_percentile, put_iv_percentile, skew_percentile))
            else "initial_protection_demand_rules"
        ),
        "insufficient_protection_demand_evidence",
    )
    bearish["initial_rules_used"] = (
        pc_percentile is None and pc_rule is not None or skew_percentile is None and skew_rule is not None
    )
    if bearish["initial_rules_used"] or pc30 is not None and ratio_coverage[2]["confidence"] == "low":
        bearish["confidence"] = "low"
    if mode != "daily":
        bearish["confidence"] = "low"  # Intraday IV is compared to prior closing observations.
    liquidity_scores = [value for _, value in liquidity_by_contract.values()]
    risk_score = weighted_score(
        [mean(liquidity_scores)] if liquidity_scores else [],
        (1,),
        "observed_quote_liquidity_rules",
        "observed_quotes_unavailable",
    )
    grade = (
        "C"
        if base_days < config.min_history_days or not primary or any(e.startswith("yfinance:") for e in chain.errors)
        else "B"
    )
    if (
        iv30 is None
        or len([v for v in iv_history if v is not None]) < config.min_history_days
        or (selected_source and selected_source[1] == "indicative")
        or skew30["feed_type"] == "indicative"
        or (put_iv_source and put_iv_source[1] == "indicative")
        or any(r.feed_type == "indicative" for r in activity_rows.values())
        or (pc30 is not None and ratio_coverage[2]["confidence"] == "low")
    ):
        grade = "C"
    # A requires timestamped real OPRA IV too; Alpaca snapshots without IV timestamps cannot earn A.
    if (
        grade == "B"
        and primary[0].feed_type == "opra"
        and selected_source[1] == "opra"
        and all(
            r.iv_timestamp is not None and liquidity(r, now, session_date, config)["quote_status"] == "valid"
            for r in groups[selected_source]
            if iv_usable(r, now, config)
        )
    ):
        grade = "A"

    def stock_event(kind, value, reference, severity, reason, source, feed):
        candidates.append(
            {
                "contract_symbol": "",
                "event_type": kind,
                "value": value,
                "reference": reference,
                "severity": severity,
                "source": source,
                "feed_type": feed,
                "data_time": chain.observed_at.isoformat(),
                "direction": "protection_demand" if "SKEW" in kind else "volatility",
                "explanation": reason,
            }
        )

    if skew30["value"] is not None and skew30["value"] >= config.skew_alert:
        stock_event(
            "BEARISH_SKEW_SPIKE",
            skew30["value"],
            {"change": skew_change, **skew30},
            80,
            "同到期25Δ Put IV − Call IV偏高；保护可能变贵，无法确认净空头。",
            skew30["source"],
            skew30["feed_type"],
        )
    if iv_percentile is not None and iv_percentile >= config.percentile_alert:
        stock_event(
            "IV_SPIKE",
            iv30,
            {"percentile": iv_percentile, "sample_days": len(iv_history)},
            iv_percentile,
            "标准化30D ATM IV历史分位数升高。",
            *selected_source,
        )
    for key in source_order:
        valid_term = [t for t in term if t["atm_iv"] is not None and (t["source"], t["feed_type"]) == key]
        if len(valid_term) >= 2 and valid_term[0]["atm_iv"] - valid_term[-1]["atm_iv"] >= config.term_inversion_alert:
            stock_event(
                "IV_TERM_INVERSION",
                valid_term[0]["atm_iv"] - valid_term[-1]["atm_iv"],
                {"front": valid_term[0], "back": valid_term[-1]},
                75,
                "同来源短期限ATM IV高于长期限；注意实际期限与事件驱动。",
                *key,
            )
    rv = realized_volatility(closes)
    limitations = list(dict.fromkeys(chain.errors + [note for row in rows for note in row.limitations]))
    if iv30 is None:
        limitations.append("valid_30d_atm_iv_unavailable")
    if base_days < config.min_history_days:
        limitations.append(f"历史预热：{base_days}/{config.min_history_days}个可比交易日")
    if any(
        r["confidence"] == "low" and r["valid_put_contracts"] + r["valid_call_contracts"] > 0 for r in ratio_coverage
    ):
        limitations.append("partial_put_call_volume_coverage")
    return {
        "symbol": chain.symbol,
        "trade_date": session_date.isoformat(),
        "observed_at": chain.observed_at.isoformat(),
        "computed_at": now.isoformat(),
        "rule_version": config.rule_version,
        "mode": mode,
        "underlying_price": next(
            (
                r.underlying_price
                for r in rows
                if r.underlying_price is not None and isfinite(r.underlying_price) and r.underlying_price > 0
            ),
            None,
        ),
        "scores": {"bearish_demand": bearish, "unusual_activity": activity, "liquidity_risk": risk_score},
        "evidence_grade": grade,
        "direction": "protection_demand_reference",
        "confidence": "low" if grade == "C" else "medium",
        "history_days": base_days,
        "volume_history_days": len({h["trade_date"] for h in comparable}),
        "volatility_comparison": "prior_daily_closes" if mode != "daily" else "same_phase_daily",
        "status": "warming_up" if base_days < config.min_history_days else "ready",
        "iv_30d": iv30,
        "iv_30d_method": iv30_method,
        "iv_source": list(selected_source or ()),
        "iv_percentile": iv_percentile,
        "iv_sample_count": len([v for v in iv_history if v is not None]),
        "rv_20d": rv,
        "iv_rv_ratio": iv30 / rv if iv30 is not None and rv else None,
        "rv_method": "20 log returns; sample std × sqrt(252); IV ACT/365",
        "term_structure": term,
        "skew_terms": target_skews,
        "skew_30d": skew30["value"],
        "skew_source": [skew30["source"], skew30["feed_type"]],
        "skew_change": skew_change,
        "put_call_ratios": ratios,
        "put_call_volume_ratio": pc30,
        "put_iv": put_iv,
        "put_iv_source": put_iv_source,
        "volume_source": primary[0].data_source if primary else None,
        "volume_feed": primary[0].feed_type if primary else None,
        "activity_sources": sorted({r.data_source + ":" + r.feed_type for r in activity_rows.values()}),
        "put_premium_estimate": put_premium,
        "premium_volume": (
            sum(c["premium_volume"] for c in contracts if c["premium_volume"] is not None)
            if any(c["premium_volume"] is not None for c in contracts)
            else None
        ),
        "premium_volume_method": "reported_opra_daily_vwap_times_volume",
        "limitations": limitations,
        "coverage": {
            **chain.coverage,
            "put_call_volume": ratio_coverage,
            "provider_term_structure": {":".join(key): value for key, value in source_metrics.items()},
            "iv_30d_reference_expirations": [t["expiration"] for t in iv30_references],
        },
        "contracts": contracts,
        "events": [
            {
                **c,
                "evidence_grade": "C" if c["feed_type"] == "indicative" else grade,
                "confidence": "low" if grade == "C" else "medium",
            }
            for c in candidates
        ],
        "risk_summary": "看跌需求评分衡量保护需求证据，不是下跌概率；成交方向与净开仓无法由链快照确认。",
        "order_flow": {"available": False, "reason": "historical_opra_trade_quote_permission_not_verified"},
    }
