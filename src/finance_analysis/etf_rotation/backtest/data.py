"""Read-only OHLCV loading for the CN ETF rotation backtest."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
from finance_analysis.etf_rotation.backtest.types import OhlcvBar

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
_DOCKER_DB_HOSTS = frozenset({"postgres", "finance-analysis-db"})


def expand_env_placeholders(value: str) -> str:
    return _PLACEHOLDER.sub(lambda match: os.environ.get(match.group(1), match.group(0)), value)


def resolve_database_url(raw: str, *, host_override: str | None = "127.0.0.1") -> str:
    """Expand ${VAR} placeholders and rewrite Compose DB hostnames for host-side runs."""
    expanded = expand_env_placeholders((raw or "").strip())
    if not expanded:
        raise ValueError("DATABASE_URL is empty")
    url = make_url(expanded)
    if host_override and url.host in _DOCKER_DB_HOSTS:
        url = url.set(host=host_override)
    return url.render_as_string(hide_password=False)


def create_readonly_engine(database_url: str) -> Engine:
    return create_engine(resolve_database_url(database_url), pool_pre_ping=True)


def load_ohlcv(
    session: Session,
    codes: Sequence[str],
    start: date,
    end: date,
    *,
    market: str = "CN",
) -> dict[str, list[OhlcvBar]]:
    selected = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
    if not selected or start > end:
        return {}
    rows = session.execute(
        select(
            MarketDataSymbol.code,
            StockDaily.date,
            StockDaily.open,
            StockDaily.high,
            StockDaily.low,
            StockDaily.close,
            StockDaily.volume,
            StockDaily.amount,
            StockDaily.suspended,
        )
        .join(StockDaily, StockDaily.symbol_id == MarketDataSymbol.id)
        .where(
            MarketDataSymbol.market == market,
            MarketDataSymbol.code.in_(selected),
            StockDaily.date.between(start, end),
        )
        .order_by(MarketDataSymbol.code, StockDaily.date)
    ).all()
    bars: dict[str, list[OhlcvBar]] = defaultdict(list)
    for code, trade_date, open_, high, low, close, volume, amount, suspended in rows:
        bars[str(code)].append(
            OhlcvBar(
                trade_date=trade_date,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
                amount=None if amount is None else float(amount),
                suspended=bool(suspended),
            )
        )
    return dict(bars)


def load_ohlcv_from_url(
    database_url: str,
    codes: Iterable[str],
    start: date,
    end: date,
    *,
    market: str = "CN",
) -> dict[str, list[OhlcvBar]]:
    engine = create_readonly_engine(database_url)
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as session:
            return load_ohlcv(session, list(codes), start, end, market=market)
    finally:
        engine.dispose()


__all__ = [
    "create_readonly_engine",
    "expand_env_placeholders",
    "load_ohlcv",
    "load_ohlcv_from_url",
    "resolve_database_url",
]
