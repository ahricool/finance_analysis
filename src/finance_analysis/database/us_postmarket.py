"""Seed review inputs into daily ingestion without enlarging strategy universes."""

import sqlalchemy as sa

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe, UniverseMember
from finance_analysis.market_review.us_postmarket_symbols import US_POSTMARKET_BENCHMARKS, US_POSTMARKET_SECTOR_ETFS

MEMBER_SOURCE = "US_POSTMARKET_REVIEW"


def seed_us_postmarket_symbols(connection) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = sqlite_insert if connection.dialect.name == "sqlite" else pg_insert
    connection.execute(
        insert(Universe.__table__)
        .values(key="us_daily_sync", name="美股日线同步", market="US", universe_type="STRATEGY", enabled=True, config={})
        .on_conflict_do_nothing(index_elements=["key"])
    )
    universe_id = connection.scalar(sa.select(Universe.id).where(Universe.key == "us_daily_sync"))
    for code, name in (US_POSTMARKET_BENCHMARKS | US_POSTMARKET_SECTOR_ETFS).items():
        connection.execute(
            insert(Instrument.__table__)
            .values(
                code=code, native_code=code.removesuffix(".US"), market="US", name=name,
                instrument_type="ETF", currency="USD", listing_status="ACTIVE", source="CURATED", metadata={},
            )
            .on_conflict_do_nothing(index_elements=["code"])
        )
        instrument_id = connection.scalar(sa.select(Instrument.id).where(Instrument.code == code))
        connection.execute(
            insert(UniverseMember.__table__)
            .values(universe_id=universe_id, instrument_id=instrument_id, source=MEMBER_SOURCE, metadata={})
            .on_conflict_do_nothing(index_elements=["universe_id", "instrument_id"])
        )
