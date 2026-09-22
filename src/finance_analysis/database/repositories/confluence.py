"""Bounded formal-source reads and atomic confluence generations."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, delete, text, and_
from finance_analysis.database.models.confluence import ConfluenceRun, ConfluenceSnapshot
from finance_analysis.database.models.industry_strength import IndustryStrengthConstituent
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.quant import ModelSignal
from finance_analysis.database.models.stock import Instrument
from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES
from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.database.repositories.quant import QuantRepository


def values(row, fields):
    return {key: getattr(row, key) for key in fields.split()}


class ConfluenceRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def instruments(self, market):
        with self.db.get_session() as session:
            return [
                values(row, "id code name")
                for row in session.scalars(
                    select(Instrument).where(Instrument.market == market, Instrument.instrument_type == "STOCK")
                )
            ]

    def trend(self, market, day):
        with self.db.get_session() as session:
            dates = list(
                session.scalars(
                    select(TrendFollowingSnapshot.trade_date)
                    .where(TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date <= day)
                    .distinct()
                    .order_by(TrendFollowingSnapshot.trade_date.desc())
                    .limit(2)
                )
            )
            if not dates:
                return []
            rows = list(
                session.scalars(
                    select(TrendFollowingSnapshot).where(
                        TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date.in_(dates)
                    )
                )
            )
            previous = {r.instrument_id: r.rank for r in rows if r.trade_date != dates[0]}
            result = []
            for row in rows:
                if row.trade_date != dates[0]:
                    continue
                item = values(
                    row,
                    "id instrument_id trade_date generated_at state trend_lifecycle trend_score "
                    "rank trend_duration_days fragility_score rs_score",
                )
                item.update({k: (row.features or {}).get(k) for k in ("trend_acceleration", "trend_quality", "rs_5d")})
                if row.instrument_id in previous:
                    item["previous_rank"] = previous[row.instrument_id]
                    item["previous_trade_date"] = dates[1]
                    # Do not call the preceding available snapshot a 1D change if sessions are missing.
                result.append(item)
            return result

    def quant(self, market, day):
        repo = QuantRepository(self.db)
        universe = repo.get_universe(DEFAULT_QUANT_UNIVERSES[market])
        if universe is None:
            return []
        with self.db.get_session() as session:
            latest = session.scalar(
                select(func.max(ModelSignal.trade_date)).where(
                    ModelSignal.market == market, ModelSignal.universe_id == universe.id, ModelSignal.trade_date <= day
                )
            )
        if latest is None:
            return []
        # Reuse the existing formal result/version selection; no live production-model lookup.
        rows = repo.latest_signals(market=market, universe_id=universe.id, trade_date=latest, limit=100000)
        return [
            values(
                row,
                "id instrument_id trade_date generated_at model_version universe_id universe_rank "
                "final_score signal predicted_return cross_section_score",
            )
            for row in rows
        ]

    def industry(self, market, day):
        if market != "CN":
            return []
        repo = IndustryStrengthRepository(self.db)
        dates = repo.dates(end=day, limit=1)
        if not dates:
            return []
        snapshots = {r["industry_code"]: r for r in repo.ranking(dates[0])}
        # This table is latest-only. A member observed after the target day cannot establish past membership.
        cutoff = datetime.combine(day + timedelta(days=1), time.min, ZoneInfo("Asia/Shanghai"))
        with self.db.get_session() as session:
            members = list(
                session.scalars(
                    select(IndustryStrengthConstituent).where(IndustryStrengthConstituent.updated_at < cutoff)
                )
            )
            result = []
            for member in members:
                row = snapshots.get(member.industry_code)
                if row is None:
                    continue
                # Preserve the exact member observation date separately from the industry result date.
                result.append(
                    {
                        k: row[k]
                        for k in (
                            "id",
                            "trade_date",
                            "updated_at",
                            "industry_code",
                            "industry_name",
                            "strength_rank",
                            "strength_score",
                            "state",
                            "rank_change_1d",
                            "rank_change_3d",
                            "rank_change_5d",
                            "momentum_acceleration_5d",
                        )
                    }
                    | {"code": member.stock_code, "members_observed_at": member.updated_at}
                )
            return result

    def dragon_tiger(self, market, day):
        if market != "CN":
            return []
        from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch
        from finance_analysis.dragon_tiger_flow.calendar import sessions_through
        from finance_analysis.dragon_tiger_flow.calculator import selected_rows, allocate, sum_known

        days = sessions_through(day, 3)
        with self.db.get_session() as session:
            batches = list(
                session.scalars(
                    select(DragonTigerFlowBatch)
                    .where(DragonTigerFlowBatch.trade_date.in_(days))
                    .order_by(DragonTigerFlowBatch.trade_date.desc())
                )
            )
            stocks = {}
            for batch in batches:
                for period in (1, 3):
                    rows, _, _ = selected_rows(batch.payload["sources"], "all", period)
                    # Reuse the domain's exact concept allocations. Categories remain overlapping.
                    allocations = allocate(rows)
                    concepts = {}
                    for allocation in allocations:
                        concepts.setdefault(allocation["concept_name"], []).append(allocation["net_value"])
                    for row in rows:
                        record = dict(
                            trade_date=batch.trade_date,
                            generated_at=batch.generated_at,
                            batch_id=batch.batch_id,
                            range_days=period,
                            net_inflow=float(row["net_value"]) if row["net_value"] is not None else None,
                            institution_net_inflow=(
                                float(row["org_net_value"]) if row["org_net_value"] is not None else None
                            ),
                            hot_money_net_inflow=(
                                float(row["hot_money_net_value"]) if row["hot_money_net_value"] is not None else None
                            ),
                            concept_flows=[
                                dict(name=name, net_inflow=sum_known(concepts[name]))
                                for name in row["concepts"]
                                if name in concepts
                            ],
                        )
                        # Latest record wins; 1D preferred to overlapping native 3D on the same day.
                        if row["symbol"] not in stocks:
                            stocks[row["symbol"]] = dict(code=row["symbol"], **record, records=[])
                        stocks[row["symbol"]]["records"].append(record)
            return list(stocks.values())

    def save(self, market, day, rows, manifest):
        with self.db.session_scope() as session:
            if session.bind.dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": 964000000 + day.toordinal() * 2 + (market == "US")},
                )
            current_run = session.get(ConfluenceRun, (market, day))
            if current_run and coerce_aware_utc(current_run.generated_at) > manifest["generated_at"]:
                return False
            session.merge(ConfluenceRun(market=market, trade_date=day, **manifest))
            # Same-day upsert and removal of obsolete members happen in one transaction.
            existing = {
                r.instrument_id: r
                for r in session.scalars(
                    select(ConfluenceSnapshot).where(
                        ConfluenceSnapshot.market == market, ConfluenceSnapshot.trade_date == day
                    )
                )
            }
            for row in rows:
                current = existing.pop(row["instrument_id"], None)
                if current is None:
                    session.add(ConfluenceSnapshot(market=market, trade_date=day, **row))
                else:
                    for key, value in row.items():
                        setattr(current, key, value)
            if existing:
                session.execute(
                    delete(ConfluenceSnapshot).where(ConfluenceSnapshot.id.in_([r.id for r in existing.values()]))
                )

        return True

    def dates(self, market):
        with self.db.get_session() as session:
            return list(
                session.scalars(
                    select(ConfluenceRun.trade_date)
                    .where(ConfluenceRun.market == market)
                    .order_by(ConfluenceRun.trade_date.desc())
                    .limit(250)
                )
            )

    def read(self, market, day=None):
        # Manifest and items from a single statement snapshot, even during a concurrent rerun.
        selected_day = (
            day
            if day is not None
            else select(func.max(ConfluenceRun.trade_date)).where(ConfluenceRun.market == market).scalar_subquery()
        )
        query = (
            select(ConfluenceRun, ConfluenceSnapshot, Instrument.code, Instrument.name)
            .outerjoin(
                ConfluenceSnapshot,
                and_(
                    ConfluenceSnapshot.market == ConfluenceRun.market,
                    ConfluenceSnapshot.trade_date == ConfluenceRun.trade_date,
                ),
            )
            .outerjoin(Instrument, Instrument.id == ConfluenceSnapshot.instrument_id)
            .where(ConfluenceRun.market == market, ConfluenceRun.trade_date == selected_day)
        )
        with self.db.get_session() as session:
            rows = session.execute(query).all()
            if not rows:
                return dict(
                    market=market,
                    trade_date=day,
                    generated_at=None,
                    algorithm_version=None,
                    source_availability={},
                    items=[],
                )
            return dict(
                values(rows[0][0], "market trade_date generated_at algorithm_version source_availability"),
                items=[
                    dict(
                        values(
                            row,
                            "instrument_id confluence_score available_weight available_signal_count "
                            "positive_signal_count eligible strong_confluence signals reasons generated_at",
                        ),
                        code=code,
                        name=name,
                    )
                    for _, row, code, name in rows
                    if row is not None
                ],
            )
