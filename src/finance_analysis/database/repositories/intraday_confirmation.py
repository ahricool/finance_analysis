"""Freeze prior-session selected confluence, Trend 20D top 30 and ETF top 5."""

from sqlalchemy import select
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.confluence import ConfluenceSnapshot
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot
from finance_analysis.database.repositories.confluence import ConfluenceRepository, values
from finance_analysis.intraday_confirmation import config as c


class CandidateRepository:
    def __init__(self, db_manager=None):
        self.db = ConfluenceRepository(db_manager).db

    def candidates(self, market, day, cutoff):
        result = {}
        with self.db.get_session() as session:
            sources = (
                (
                    ConfluenceSnapshot,
                    "confluence",
                    ConfluenceSnapshot.eligible.is_(True),
                    ConfluenceSnapshot.confluence_score.desc(),
                ),
                (
                    TrendFollowingSnapshot,
                    "trend",
                    (TrendFollowingSnapshot.trend_period == 20)
                    & (TrendFollowingSnapshot.rank <= c.TREND_TOP)
                    & (TrendFollowingSnapshot.rank > 0),
                    TrendFollowingSnapshot.rank.asc(),
                ),
                (
                    ETFMomentumSnapshot,
                    "etf",
                    (ETFMomentumSnapshot.rank <= c.ETF_TOP) & (ETFMomentumSnapshot.rank > 0),
                    ETFMomentumSnapshot.rank.asc(),
                ),
            )
            for model, source, condition, ordering in sources:
                rows = session.execute(
                    select(model, Instrument.code, Instrument.name, Instrument.instrument_type)
                    .join(Instrument, Instrument.id == model.instrument_id)
                    .where(
                        model.market == market,
                        model.trade_date == day,
                        model.generated_at < cutoff,
                        Instrument.market == market,
                        Instrument.listing_status == "ACTIVE",
                        Instrument.instrument_type.in_(["STOCK", "ETF"]),
                        condition,
                    )
                    .order_by(ordering, Instrument.code)
                ).all()
                for row, code, name, kind in rows:
                    # A formal ETF rotation member is an ETF even when the instrument directory is coarsely typed STOCK.
                    reasons = (
                        [f"ETF轮动正式综合排名第 {row.rank}"]
                        if source == "etf"
                        else (
                            [f"20日趋势正式综合排名第 {row.rank}", *(row.reasons or [])]
                            if source == "trend"
                            else row.reasons or ["昨日共振精选"]
                        )
                    )
                    item = result.setdefault(
                        code,
                        dict(
                            code=code,
                            name=name,
                            instrument_type=kind,
                            candidate_source=source,
                            candidate_sources=[],
                            source_evidence=[],
                            candidate_trade_date=day,
                            candidate_reason=[],
                            source_generated_at=row.generated_at,
                        ),
                    )
                    if source == "etf":
                        item["instrument_type"] = "ETF"
                    item["candidate_sources"].append(source)
                    item["candidate_reason"].extend(reasons)
                    item["source_evidence"].append(
                        dict(
                            source=source,
                            trade_date=day,
                            generated_at=row.generated_at,
                            rank=getattr(row, "rank", None),
                            reasons=reasons,
                        )
                    )
            codes = list(result)
            official = (
                {
                    row.code: values(
                        row, "state trend_lifecycle trend_score fragility_score features trend_duration_days trade_date"
                    )
                    for row in session.scalars(
                        select(TrendFollowingSnapshot).where(
                            TrendFollowingSnapshot.trend_period == 20,
                            TrendFollowingSnapshot.market == market,
                            TrendFollowingSnapshot.trade_date == day,
                            TrendFollowingSnapshot.code.in_(codes),
                            TrendFollowingSnapshot.generated_at < cutoff,
                        )
                    )
                }
                if codes
                else {}
            )
        for row in result.values():
            row["official_trend"] = official.get(row["code"])
        return list(result.values())
