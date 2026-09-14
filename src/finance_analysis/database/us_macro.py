"""Idempotent system Universe seed shared by startup and migration."""

import sqlalchemy as sa

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe, UniverseInclude, UniverseMember
from finance_analysis.macro.config import MACRO_INSTRUMENTS, UNIVERSE_KEY


def seed_us_macro(connection) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = sqlite_insert if connection.dialect.name == "sqlite" else pg_insert
    for key, name in ((UNIVERSE_KEY, "US Macro"), ("us_daily_sync", "美股日线同步")):
        connection.execute(
            insert(Universe.__table__)
            .values(key=key, name=name, market="US", universe_type="STRATEGY", enabled=True, config={})
            .on_conflict_do_nothing(index_elements=["key"])
        )
    ids = dict(
        connection.execute(
            sa.select(Universe.key, Universe.id).where(Universe.key.in_([UNIVERSE_KEY, "us_daily_sync"]))
        ).all()
    )
    for code, config in MACRO_INSTRUMENTS.items():
        connection.execute(
            insert(Instrument.__table__)
            .values(
                code=code,
                native_code=code.removesuffix(".US"),
                market="US",
                name=config.name,
                instrument_type=config.instrument_type,
                currency="USD",
                listing_status="ACTIVE",
                source="CURATED",
                metadata={},
            )
            .on_conflict_do_update(
                index_elements=["code"], set_={"instrument_type": config.instrument_type, "currency": "USD"}
            )
        )
        instrument_id = connection.execute(sa.select(Instrument.id).where(Instrument.code == code)).scalar_one()
        connection.execute(
            insert(UniverseMember.__table__)
            .values(universe_id=ids[UNIVERSE_KEY], instrument_id=instrument_id, source="CURATED", metadata={})
            .on_conflict_do_nothing(index_elements=["universe_id", "instrument_id"])
        )
    connection.execute(
        insert(UniverseInclude.__table__)
        .values(universe_id=ids["us_daily_sync"], included_universe_id=ids[UNIVERSE_KEY])
        .on_conflict_do_nothing(index_elements=["universe_id", "included_universe_id"])
    )
