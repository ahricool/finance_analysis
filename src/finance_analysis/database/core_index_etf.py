"""Core index ETF ingestion coverage, independent of strategy candidate pools."""

import sqlalchemy as sa

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.universe import Universe, UniverseMember

MEMBER_SOURCE = "CORE_INDEX_ETF"
CORE_INDEX_ETFS = {
    "CN": {
        "510050.SH": "上证50ETF华夏",
        "510300.SH": "沪深300ETF华泰柏瑞",
        "510500.SH": "中证500ETF南方",
        "512100.SH": "中证1000ETF南方",
        "159531.SZ": "中证2000ETF南方",
        "159338.SZ": "中证A500ETF国泰",
        "159915.SZ": "创业板ETF易方达",
        "159949.SZ": "创业板50ETF华安",
        "588000.SH": "科创50ETF华夏",
        "159920.SZ": "恒生ETF华夏",
        "513180.SH": "恒生科技ETF华夏",
    },
    "US": {
        "SPY.US": "标普500ETF-SPDR",
        "QQQ.US": "纳斯达克100ETF-Invesco",
        "DIA.US": "道琼斯工业平均指数ETF-SPDR",
        "IWM.US": "罗素2000ETF-iShares",
        "MDY.US": "标普400中盘ETF-SPDR",
        "VTI.US": "美国全市场ETF-Vanguard",
        "VT.US": "全球股票ETF-Vanguard",
    },
}


def seed_core_index_etfs(connection) -> None:
    """Add missing identities/memberships; preserve existing reference metadata and bars."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = sqlite_insert if connection.dialect.name == "sqlite" else pg_insert
    for market, members in CORE_INDEX_ETFS.items():
        key = f"{market.lower()}_daily_sync"
        connection.execute(
            insert(Universe.__table__)
            .values(
                key=key, name=f"{market}日线同步", market=market, universe_type="STRATEGY", enabled=True,
                config=sa.literal_column("'{}'"),
                created_at=sa.func.now(), updated_at=sa.func.now(),
            )
            .on_conflict_do_nothing(index_elements=["key"])
        )
        for code, name in members.items():
            connection.execute(
                insert(Instrument.__table__)
                .values(
                    code=code, native_code=code.rsplit(".", 1)[0], market=market, name=name,
                    instrument_type="ETF", currency="CNY" if market == "CN" else "USD",
                    listing_status="ACTIVE", source="CURATED", metadata=sa.literal_column("'{}'"),
                    created_at=sa.func.now(), updated_at=sa.func.now(),
                )
                .on_conflict_do_update(index_elements=["code"], set_={"instrument_type": "ETF"})
            )
            connection.execute(
                insert(UniverseMember.__table__)
                .from_select(
                    ["universe_id", "instrument_id", "source", "metadata", "created_at", "updated_at"],
                    sa.select(
                        Universe.id, Instrument.id, sa.literal(MEMBER_SOURCE), sa.literal_column("'{}'"),
                        sa.func.now(), sa.func.now(),
                    )
                    .select_from(Universe.__table__.join(Instrument.__table__, Instrument.code == code))
                    .where(Universe.key == key),
                )
                .on_conflict_do_nothing(index_elements=["universe_id", "instrument_id"])
            )
