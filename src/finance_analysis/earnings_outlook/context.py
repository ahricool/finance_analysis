"""Bounded structured inputs, never substitutes remembered or fabricated live numbers."""

import statistics
from datetime import timedelta

from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.core.time import utc_now
from finance_analysis.market_review.us_postmarket_symbols import US_POSTMARKET_SECTOR_ETFS
from finance_analysis.market_review.trading_calendar import get_market_session_bounds
from .rules import NY, number, timestamp, schedule, trading_days
from .facts import raw_facts


def consensus(event):
    facts = raw_facts(event)
    result = {k: facts.get("consensus", {}).get(k) for k in ("eps", "revenue")}
    if result["eps"] is None and event.eps_estimate is not None:
        result["eps"] = dict(
            value=event.eps_estimate,
            quarter=event.reporting_period,
            currency=event.currency,
            unit="per_share",
            basis=None,
            source=event.provider,
            as_of=None,
            observed_at=str(event.last_seen_at),
            note="日历未提供 EPS 口径及预期更新时间",
        )
    return result


def research_context(context):
    """One company/event's operating evidence; price context belongs to outlook."""
    keys = (
        "event",
        "time_certainty",
        "company",
        "data_cutoff",
        "consensus",
        "guidance_evidence",
        "analyst_revisions",
        "historical_earnings",
    )
    return {key: context[key] for key in keys if key in context}


def outlook_context(context):
    """Keep company bars, but use existing summaries for shared market series.

    Copy nested mappings: concurrent events share the original public snapshot.
    The returned projection is both sent to the model and persisted as its input.
    """
    market = dict(context.get("market") or {})
    for group in ("benchmarks", "sector_performance"):
        if group in market:
            market[group] = {
                symbol: {key: value for key, value in series.items() if key != "bars"}
                for symbol, series in market[group].items()
            }
    return {**context, "market": market}


class ContextCollector:
    def __init__(self, repo, market=None):
        self.repo, self.market = repo, market or MarketDataService()

    def bars(self, symbols, now):
        days = trading_days(now.astimezone(NY).date() - timedelta(days=60), now.astimezone(NY).date())
        complete = [d for d in days if get_market_session_bounds("us", d)[1] <= now][-30:]
        if not complete:
            return {}
        result = self.market.get_daily_bars(
            symbols, complete[0], complete[-1], adjustment="forward", source_policy="db_only"
        )
        data = {}
        for symbol, rows in result.data.items():
            rows = sorted((r for r in rows if r.trade_date in complete), key=lambda r: r.trade_date)[-30:]
            if not rows:
                continue
            returns = [b.close / a.close - 1 for a, b in zip(rows, rows[1:]) if a.close > 0]
            trs = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(rows, rows[1:])]
            data[symbol] = dict(
                bars=[
                    dict(date=str(r.trade_date), open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
                    for r in rows
                ],
                return_pct=(rows[-1].close / rows[0].close - 1) * 100,
                volatility=statistics.stdev(returns) if len(returns) > 1 else None,
                atr14=statistics.mean(trs[-14:]) if len(trs) >= 14 else None,
                sessions=len(rows),
                as_of=str(rows[-1].trade_date),
            )
        return data

    def public(self, now):
        missing = []
        try:
            benchmarks = self.bars(["SPY.US", "QQQ.US", *US_POSTMARKET_SECTOR_ETFS], now)
        except Exception:
            benchmarks = {}
            missing.append("SPY/QQQ DB 日线不可用")
        # Existing public snapshots are read in a single short transaction.
        return dict(
            benchmarks={k: v for k, v in benchmarks.items() if k in {"SPY.US", "QQQ.US"}},
            sector_performance={
                k: dict(name=US_POSTMARKET_SECTOR_ETFS[k], **v)
                for k, v in benchmarks.items()
                if k in US_POSTMARKET_SECTOR_ETFS
            },
            **self.repo.market_context(now),
            missing_data=missing,
        )

    def collect(self, event, member, now, window, public):
        missing = list(public.get("missing_data", []))
        quote = None
        try:
            quote = self.market.get_realtime_quotes([member["symbol"]]).data.get(member["symbol"])
        except Exception:
            missing.append("最新报价读取失败")
        at = timestamp(quote.quote_time) if quote else None
        price = number(quote.price) if quote else None
        if not at or at > utc_now() or at >= window["cutoff"] or not price or price <= 0:
            price = None
            missing.append("价格或报价时间不可用")
        session = "unknown"
        if at:
            local = at.astimezone(NY)
            if local.date() in trading_days(local.date(), local.date()):
                opening, closing = get_market_session_bounds("us", local.date())
                session = "premarket" if local < opening else "regular" if local <= closing else "postmarket"
            else:
                session = "closed"
        try:
            technical = self.bars([member["symbol"]], now).get(member["symbol"])
        except Exception:
            technical = None
        if not technical or technical["sessions"] < 15:
            missing.append("不足15个完整交易日技术数据")
        facts = raw_facts(event)
        for key in ("analyst_revisions", "options_implied_range", "historical_reactions", "guidance"):
            if not facts.get(key):
                missing.append(f"{key}: 结构化数据不可用")
        return dict(
            event=schedule(event),
            time_certainty=(
                "explicit"
                if event.event_datetime
                else "session_only" if event.market_session in {"bmo", "amc"} else "date_only"
            ),
            company=member,
            data_cutoff=now.isoformat(),
            target_trading_date=str(window["target_trading_date"]),
            provisional=window["provisional"],
            assumption=window["assumption"],
            reference_price=price,
            reference_price_at=at.isoformat() if at else None,
            reference_price_session=session,
            price_stale=not at or now - at > timedelta(hours=24),
            technical=technical,
            market=public,
            consensus=consensus(event),
            valuation={"pe": quote.pe_ratio if quote else None, "pb": quote.pb_ratio if quote else None},
            historical_earnings=self.repo.history_events(event.symbol, event.event_date),
            guidance_evidence=facts.get("guidance"),
            analyst_revisions=facts.get("analyst_revisions"),
            options_implied_range=facts.get("options_implied_range"),
            historical_reactions=facts.get("historical_reactions"),
            missing_data=missing,
        )

    def actual(self, event, version, now):
        """Price-only review: exact closed sessions, DB-only, no calendar provider or LLM."""
        target = version.target_trading_date
        actual = dict(ohlc=None, previous_close=None, target_trading_date=str(target), missing_reason=None)
        if now < get_market_session_bounds("us", target)[1]:
            actual["missing_reason"] = "等待财报后目标交易日收盘"
            return actual
        sessions = trading_days(target - timedelta(days=30), target)
        previous = next((day for day in reversed(sessions) if day < target), None)
        if previous is None:
            raise ValueError("Previous trading session unavailable")
        actual["previous_trading_date"] = str(previous)
        result = self.market.get_daily_bars(
            [event.symbol], previous, target, adjustment="forward", source_policy="db_only"
        )
        rows = {row.trade_date: row for row in result.data.get(event.symbol, [])}
        row, prior = rows.get(target), rows.get(previous)
        if row and all(number(getattr(row, k)) is not None for k in ("open", "high", "low", "close")):
            if 0 < row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high:
                actual["ohlc"] = dict(
                    date=str(target),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    adjustment="forward",
                    session="regular",
                )
        if prior and number(prior.close) is not None and prior.close > 0:
            actual["previous_close"] = prior.close
        if actual["ohlc"] is None or actual["previous_close"] is None:
            actual["missing_reason"] = "等待目标交易日及前一交易日完整数据库日线"
        return actual
