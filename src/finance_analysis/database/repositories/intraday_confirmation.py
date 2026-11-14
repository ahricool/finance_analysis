"""Freeze prior-session confluence, Trend top 30, ETF top 5 and formal buy points."""

from sqlalchemy import select
from finance_analysis.trend_following.opportunity_inputs import formal_opportunities, CANDIDATE_LIMIT, POLICY_VERSION
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
                    (TrendFollowingSnapshot.trend_period == 10)
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
                            [f"10日趋势正式综合排名第 {row.rank}", *(row.reasons or [])]
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
            # Read only the prior-session formal snapshots available before freeze.
            opportunity_rows = (
                session.execute(
                    select(
                        TrendFollowingSnapshot.code,
                        TrendFollowingSnapshot.trade_date,
                        TrendFollowingSnapshot.trend_period,
                        TrendFollowingSnapshot.generated_at,
                        TrendFollowingSnapshot.features["opportunities"].label("opportunities"),
                        Instrument.name,
                        Instrument.instrument_type,
                    )
                    .join(Instrument, Instrument.id == TrendFollowingSnapshot.instrument_id)
                    .where(
                        TrendFollowingSnapshot.market == market,
                        TrendFollowingSnapshot.trade_date == day,
                        TrendFollowingSnapshot.trend_period.in_([10, 20, 40]),
                        TrendFollowingSnapshot.generated_at < cutoff,
                        Instrument.market == market,
                        Instrument.listing_status == "ACTIVE",
                        Instrument.instrument_type.in_(["STOCK", "ETF"]),
                    )
                )
                .mappings()
                .all()
            )
            documents = [dict(row, features={"opportunities": row["opportunities"]}) for row in opportunity_rows]
            metadata = {row["code"]: row for row in opportunity_rows}
            selected = [item for item in formal_opportunities(documents, day, cutoff) if item["primary"]][
                :CANDIDATE_LIMIT
            ]
            for rank, opportunity in enumerate(selected, 1):
                code = opportunity["code"]
                meta = metadata[code]
                reasons = [f"昨日正式买点机会第 {rank}，质量 {opportunity['primary']['quality_score']:g}"]
                generated = opportunity["primary"]["source_generated_at"]
                item = result.setdefault(
                    code,
                    dict(
                        code=code,
                        name=meta["name"],
                        instrument_type=meta["instrument_type"],
                        candidate_source="opportunities",
                        candidate_sources=[],
                        source_evidence=[],
                        candidate_trade_date=day,
                        candidate_reason=[],
                        source_generated_at=generated,
                    ),
                )
                item["candidate_sources"].append("opportunities")
                item["candidate_reason"].extend(reasons)
                item["source_evidence"].append(
                    dict(
                        source="opportunities",
                        trade_date=day,
                        generated_at=generated,
                        rank=rank,
                        reasons=reasons,
                        policy_version=POLICY_VERSION,
                        opportunities=opportunity["branches"],
                        covered_periods=opportunity["covered_periods"],
                    )
                )
            codes = list(result)
            official = (
                {
                    row.code: values(
                        row,
                        "trend_period state trend_lifecycle trend_score fragility_score features trend_duration_days trade_date",
                    )
                    for row in session.scalars(
                        select(TrendFollowingSnapshot).where(
                            TrendFollowingSnapshot.trend_period == 10,
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
