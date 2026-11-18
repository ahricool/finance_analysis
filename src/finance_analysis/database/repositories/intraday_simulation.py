"""One transaction and database advisory lock per symbol; no shared Sessions."""

from datetime import date
from sqlalchemy import or_, select, text
from finance_analysis.database.models.intraday_simulation import (
    IntradaySimulationState as State,
    IntradaySimulationTrade as Trade,
    IntradaySimulationEvent as Event,
)
from finance_analysis.database.session import DatabaseManager
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.simulation import dt, statistics, transition


def process(symbol, result, quote, now):
    with DatabaseManager.get_instance().session_scope() as session:
        # Lock also covers absent state rows and serializes independent Streamer instances.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "intraday-simulation:" + symbol}
        )
        row = session.get(State, symbol)
        previous = row.payload if row else {}
        if previous.get("calculated_at") and dt(previous["calculated_at"]) >= now:
            return previous
        state, events = transition(previous, symbol, result, quote, now)
        if row is None:
            session.add(State(symbol=symbol, payload=state))
        else:
            row.payload = state
        for event in events:
            session.add(Event(symbol=symbol, occurred_at=now, payload=event))
            if event["kind"] == "entry":
                trade = event["trade"]
                session.add(
                    Trade(
                        id=trade["id"],
                        symbol=symbol,
                        trading_date=date.fromisoformat(trade["trading_date"]),
                        process_id=trade["process_id"],
                        status="open",
                        payload=trade,
                    )
                )
            elif event["kind"] == "exit":
                trade = session.get(Trade, event["trade_id"])
                trade.status, trade.payload = "closed", event["trade"]
        return state


def open_retired_symbols():
    """Continue price-driven exits for positions that predate an observation pool change."""
    with DatabaseManager.get_instance().session_scope() as session:
        return set(session.scalars(select(Trade.symbol).where(Trade.status == "open", Trade.symbol.not_in(SYMBOLS))))


def read(day, after_event_id=None):
    with DatabaseManager.get_instance().session_scope() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        states = [r.payload for r in session.scalars(select(State)) if r.symbol in SYMBOLS or r.payload.get("position")]
        trades = [
            r.payload for r in session.scalars(select(Trade).where(Trade.trading_date == day, Trade.status == "closed"))
        ]
        # Full durable day snapshot on every reconnect: event IDs deduplicate; no cursor race or loss.
        from finance_analysis.market_stream.session import session_bounds

        bounds = session_bounds("US", day)
        query = select(Event).order_by(Event.id.desc())
        if bounds:
            since = Event.occurred_at >= bounds[0]
            query = query.where(or_(since, Event.id > after_event_id) if after_event_id is not None else since)
        events = [dict(id=r.id, **r.payload) for r in session.scalars(query)]
        return dict(states=states, trades=trades, events=events, statistics=statistics(trades))


def references(day):
    """Optional DB-only context. Missing coverage is explicitly unknown, never neutral."""
    from finance_analysis.database.models.stock import Instrument, StockDaily
    from finance_analysis.database.models.market_calendar import FinanceEvent

    with DatabaseManager.get_instance().session_scope() as session:
        daily = list(
            session.scalars(
                select(StockDaily)
                .join(Instrument)
                .where(Instrument.code == "QQQ.US", StockDaily.date < day)
                .order_by(StockDaily.date.desc())
                .limit(20)
            )
        )
        background = dict(label="未知", as_of=None, reason="QQQ最近已完成日线不足20根")
        if len(daily) == 20:
            mean = sum(r.close for r in daily) / 20
            change = daily[0].close / mean - 1
            background = dict(
                label="偏多" if change > 0.005 else "偏空" if change < -0.005 else "震荡",
                as_of=daily[0].date.isoformat(),
                reason="最近已存完成日线收盘相对20日均线，±0.5%为震荡；仅供参考",
            )
        events = [
            dict(
                title=e.title,
                at=e.event_datetime.isoformat(),
                as_of=e.last_seen_at.isoformat(),
                reason="已有宏观日历事件，临近发布可能增加波动；不参与入场门槛",
            )
            for e in session.scalars(
                select(FinanceEvent).where(
                    FinanceEvent.calendar_type == "macro",
                    FinanceEvent.market == "US",
                    FinanceEvent.event_date == day,
                    FinanceEvent.event_datetime.is_not(None),
                )
            )
        ]
        return dict(
            background=background,
            macro=events,
            macro_status="已存事件，覆盖可能不完整" if events else "暂无可靠时间事件，覆盖未知",
        )
