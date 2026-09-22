"""Signal Center pulls formal evidence; source tasks never publish to this module."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, and_, func
from finance_analysis.database.models.signal_center import SignalCenterRun
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot, TrendFollowingSummary
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot, ETFMarketRotationSnapshot
from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot, IndustryStrengthConstituent
from finance_analysis.database.models.task import TaskRecord
from finance_analysis.database.repositories.confluence import ConfluenceRepository, values
from finance_analysis.confluence.service import json_safe


class SignalCenterRepository(ConfluenceRepository):
    def trend(self, market, day):
        with self.db.get_session() as session:
            fields = (
                "id instrument_id code trade_date generated_at rank state setup alpha_score trend_score "
                "rs_score breakout_score reference_price features trend_lifecycle trend_duration_days fragility_score"
            )
            query = select(*(getattr(TrendFollowingSnapshot, k) for k in fields.split())).where(
                TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date == day
            )
            result = [dict(row._mapping) for row in session.execute(query)]
            previous_day = session.scalar(
                select(func.max(TrendFollowingSnapshot.trade_date)).where(
                    TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date < day
                )
            )
            previous = {
                r.code: r
                for r in session.execute(
                    select(
                        TrendFollowingSnapshot.code, TrendFollowingSnapshot.rank, TrendFollowingSnapshot.state
                    ).where(TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date == previous_day)
                )
            }
            for item in result:
                old = previous.get(item["code"])
                if old:
                    item.update(
                        previous_rank=old.rank,
                        previous_state=old.state,
                        previous_trade_date=previous_day,
                        previous_population=len(previous),
                        rank_change=old.rank - item["rank"],
                    )
            return result

    def industry(self, market, day):
        if market != "CN":
            return []
        latest = select(func.max(IndustryStrengthSnapshot.trade_date)).scalar_subquery()
        fields = (
            "id trade_date industry_code industry_name strength_rank strength_score state "
            "rank_change_1d rank_change_3d rank_change_5d momentum_acceleration_5d rs_5d rs_10d "
            "members_observed_at"
        )
        query = (
            select(
                *(getattr(IndustryStrengthSnapshot, k) for k in fields.split()),
                IndustryStrengthSnapshot.updated_at.label("generated_at"),
                IndustryStrengthConstituent.stock_code.label("code"),
                IndustryStrengthConstituent.trend_rank,
            )
            .join(
                IndustryStrengthConstituent,
                and_(
                    IndustryStrengthSnapshot.industry_code == IndustryStrengthConstituent.industry_code,
                    IndustryStrengthSnapshot.updated_at == IndustryStrengthConstituent.updated_at,
                ),
            )
            .where(
                IndustryStrengthSnapshot.trade_date == day,
                IndustryStrengthSnapshot.trade_date == latest,
                IndustryStrengthSnapshot.members_observed_at.is_not(None),
            )
        )
        with self.db.get_session() as session:
            return [dict(row._mapping) for row in session.execute(query)]

    def etf(self, market, day):
        with self.db.get_session() as session:
            rows = session.scalars(
                select(ETFMomentumSnapshot)
                .where(
                    ETFMomentumSnapshot.market == market,
                    ETFMomentumSnapshot.trade_date == day,
                    ETFMomentumSnapshot.rank.is_not(None),
                )
                .order_by(ETFMomentumSnapshot.rank, ETFMomentumSnapshot.instrument_id)
                .limit(10)
            )
            return [
                dict(
                    values(
                        r,
                        "id trade_date generated_at rank state composite_score entry_score "
                        "overheated ret_5d ret_10d rank_change_1d trend_duration_days",
                    ),
                    code=r.instrument.code,
                )
                for r in rows
            ]

    def regime(self, market, day):
        with self.db.get_session() as session:
            result = []
            for model, fields, source in (
                (TrendFollowingSummary, "market_regime market_score data_coverage warnings", "trend"),
                (ETFMarketRotationSnapshot, "regime benchmark_trend diagnostics", "etf"),
            ):
                row = session.scalar(select(model).where(model.market == market, model.trade_date == day))
                if row:
                    result.append(dict(values(row, "trade_date generated_at " + fields), source=source))
            return result

    def dependencies(self, market, day):
        zone = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
        start = datetime.combine(day, time(), zone)
        names = {key: f"scheduled_{key}_{market.lower()}" for key in ("trend_following", "quant_daily", "etf_rotation")}
        if market == "CN":
            names["industry_strength"] = "scheduled_industry_strength_cn"
        with self.db.get_session() as session:
            rows = list(
                session.scalars(
                    select(TaskRecord)
                    .where(
                        TaskRecord.task_type.in_(names.values()),
                        TaskRecord.created_at >= start,
                        TaskRecord.created_at < start + timedelta(days=1),
                    )
                    .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
                )
            )
            result = {}
            for key, name in names.items():
                matching = [r for r in rows if r.task_type == name]
                active = next((r for r in matching if r.status in {"pending", "processing", "retrying"}), None)
                row = active or next(iter(matching), None)
                result[key] = dict(status=row.status if row else "unknown", task_id=row.task_id if row else None)
            return result

    def get(self, market, day):
        with self.db.get_session() as session:
            row = session.get(SignalCenterRun, (market, day))
            return self.serialize(row) if row else None

    @staticmethod
    def serialize(row):
        return json_safe({c.name: getattr(row, c.name) for c in row.__table__.columns})

    def history(self, limit=50, offset=0):
        with self.db.get_session() as session:
            columns = [
                getattr(SignalCenterRun, key)
                for key in (
                    "market",
                    "signal_date",
                    "status",
                    "selected_symbol",
                    "decision",
                    "confidence",
                    "created_at",
                    "completed_at",
                )
            ]
            return [
                json_safe(dict(row._mapping))
                for row in session.execute(
                    select(*columns)
                    .order_by(SignalCenterRun.signal_date.desc(), SignalCenterRun.market)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def create(self, market, day, **fields):
        # The service holds a session advisory lock. The composite PK is the final race guard.
        with self.db.session_scope() as session:
            session.add(SignalCenterRun(market=market, signal_date=day, **fields))
        return self.get(market, day)

    def finish(self, market, day, **fields):
        with self.db.session_scope() as session:
            row = session.get(SignalCenterRun, (market, day), with_for_update=True)
            if row.status in {"completed", "skipped"}:
                return
            for key, value in fields.items():
                if key not in {
                    "status",
                    "analysis",
                    "decision",
                    "selected_symbol",
                    "confidence",
                    "model",
                    "backend",
                    "raw_response",
                    "error",
                    "completed_at",
                    "screening",
                    "final_prompt",
                }:
                    raise ValueError("Cannot mutate frozen input")
                setattr(row, key, value)
