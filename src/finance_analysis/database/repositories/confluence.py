"""Bounded formal-source reads and atomic confluence generations."""

from sqlalchemy import select, func, delete, text, and_
from finance_analysis.database.models.confluence import ConfluenceRun, ConfluenceSnapshot
from finance_analysis.database.models.industry_strength import IndustryStrengthConstituent, IndustryStrengthSnapshot
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.quant import ModelSignal
from finance_analysis.database.models.stock import Instrument
from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES
from finance_analysis.core.time import coerce_aware_utc
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
                values(row, "id code name instrument_metadata")
                for row in session.scalars(
                    select(Instrument).where(
                        Instrument.market == market,
                        Instrument.instrument_type == "STOCK",
                        Instrument.listing_status == "ACTIVE",
                    )
                )
            ]

    def trend(self, market, day):
        with self.db.get_session() as session:
            dates = list(
                session.scalars(
                    select(TrendFollowingSnapshot.trade_date)
                    .where(
                        TrendFollowingSnapshot.trend_period == 20,
                        TrendFollowingSnapshot.market == market,
                        TrendFollowingSnapshot.trade_date <= day,
                    )
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
                        TrendFollowingSnapshot.trend_period == 20,
                        TrendFollowingSnapshot.market == market,
                        TrendFollowingSnapshot.trade_date.in_(dates),
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
        # Formal Industry save refreshes snapshots and latest-only members atomically
        # with the same updated_at. This proves one generation, not historical membership.
        latest = select(func.max(IndustryStrengthSnapshot.trade_date)).scalar_subquery()
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        cutoff = datetime.combine(day, time(20, 30), ZoneInfo("Asia/Shanghai"))
        fields = (
            "id trade_date updated_at industry_code industry_name strength_rank strength_score state "
            "rank_change_1d rank_change_3d rank_change_5d momentum_acceleration_5d"
        )
        query = (
            select(
                *[getattr(IndustryStrengthSnapshot, key) for key in fields.split()],
                IndustryStrengthConstituent.stock_code.label("code"),
                IndustryStrengthSnapshot.members_observed_at.label("members_observed_at"),
                IndustryStrengthConstituent.updated_at.label("membership_generation_at"),
            )
            .join(
                IndustryStrengthConstituent,
                and_(
                    IndustryStrengthSnapshot.industry_code == IndustryStrengthConstituent.industry_code,
                    IndustryStrengthSnapshot.updated_at == IndustryStrengthConstituent.updated_at,
                ),
            )
            .where(
                IndustryStrengthSnapshot.trade_date == latest,
                IndustryStrengthSnapshot.trade_date == day,
                IndustryStrengthSnapshot.members_observed_at.is_not(None),
                IndustryStrengthSnapshot.members_observed_at <= cutoff,
            )
        )
        with self.db.get_session() as session:
            return [dict(row) for row in session.execute(query).mappings()]

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

    def trend_v2(self, market, day):
        # One bounded query for all three same-date periods; no strategy reruns.
        feature_keys = ("path_score", "entry_type", "entry_score", "box_state", "box_quality", "mr_state", "mr_quality")
        query = select(
            TrendFollowingSnapshot.instrument_id,
            TrendFollowingSnapshot.code,
            TrendFollowingSnapshot.trade_date,
            TrendFollowingSnapshot.generated_at,
            TrendFollowingSnapshot.trend_period,
            TrendFollowingSnapshot.state,
            TrendFollowingSnapshot.trend_lifecycle,
            TrendFollowingSnapshot.alpha_score,
            TrendFollowingSnapshot.trend_score,
            TrendFollowingSnapshot.fragility_score,
            TrendFollowingSnapshot.rank,
            *[TrendFollowingSnapshot.features[key].label(key) for key in feature_keys],
        ).where(TrendFollowingSnapshot.market == market, TrendFollowingSnapshot.trade_date == day)
        with self.db.get_session() as session:
            result = []
            for row in session.execute(query).mappings():
                item = dict(row)
                item["features"] = {key: item.pop(key) for key in feature_keys}
                result.append(item)
            return result

    def classification(self, market, day):
        """Latest-only classifications observed no later than the formal target cutoff."""
        from datetime import datetime, time, timezone
        from zoneinfo import ZoneInfo
        from finance_analysis.database.models.industry_strength import IndustryCatalog, IndustryMembership
        from finance_analysis.stocks.industry_etf import resolve_industry_etf

        cutoff = datetime.combine(
            day,
            time(20, 30) if market == "CN" else time(23, 30),
            ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York"),
        )
        grouped = {}
        with self.db.get_session() as session:
            if market == "CN":
                for code, key, name, observed in session.execute(
                    select(
                        IndustryMembership.stock_code,
                        IndustryCatalog.industry_code,
                        IndustryCatalog.industry_name,
                        IndustryCatalog.members_observed_at,
                    )
                    .join(IndustryCatalog, IndustryCatalog.industry_code == IndustryMembership.industry_code)
                    .where(IndustryCatalog.members_observed_at <= cutoff)
                ):
                    proxy = resolve_industry_etf(market, key)
                    grouped.setdefault(code, []).append(
                        dict(
                            industry_code=key,
                            industry_name=name,
                            observed_at=observed,
                            proxy_code=proxy.etf_code,
                            proxy_reason=proxy.reason,
                        )
                    )
            elif market == "US":
                for code, metadata in session.execute(
                    select(Instrument.code, Instrument.instrument_metadata).where(
                        Instrument.market == market,
                        Instrument.instrument_type == "STOCK",
                        Instrument.listing_status == "ACTIVE",
                    )
                ):
                    classification = (metadata or {}).get("classification") or {}
                    observed = classification.get("observed_at")
                    try:
                        when = datetime.fromisoformat(observed.replace("Z", "+00:00")) if observed else None
                    except (ValueError, TypeError, AttributeError):
                        when = None
                    if not when or when.tzinfo is None or when.astimezone(timezone.utc) > cutoff:
                        continue
                    key, sector = classification.get("industry", ""), classification.get("sector")
                    if not key:
                        continue
                    proxy = resolve_industry_etf(market, key, sector=sector)
                    grouped[code] = [
                        dict(
                            industry_code=key,
                            industry_name=key,
                            sector=sector,
                            observed_at=when,
                            proxy_code=proxy.etf_code,
                            proxy_reason=proxy.reason,
                        )
                    ]
        return [
            dict(code=code, trade_date=day, industries=sorted(rows, key=lambda r: r["industry_code"]))
            for code, rows in sorted(grouped.items())
        ]

    def etf(self, market, day, *, classifications=None):
        from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot as ETF
        from finance_analysis.database.models.universe import Universe, UniverseMember
        from finance_analysis.stocks.industry_etf import MAPPING_VERSION

        classifications = self.classification(market, day) if classifications is None else classifications
        memberships = {}
        for row in classifications:
            for industry in row["industries"]:
                if industry["proxy_code"]:
                    memberships.setdefault(row["code"], {}).setdefault(industry["proxy_code"], []).append(
                        f"{industry['industry_name']}：{industry['proxy_reason']}"
                    )
        with self.db.get_session() as session:
            rows = (
                session.execute(
                    select(
                        Instrument.code,
                        Instrument.name,
                        ETF.id,
                        ETF.trade_date,
                        ETF.generated_at,
                        ETF.composite_score,
                        ETF.state,
                        ETF.rank,
                        ETF.entry_score,
                    )
                    .join(Instrument, Instrument.id == ETF.instrument_id)
                    .join(UniverseMember, UniverseMember.instrument_id == ETF.instrument_id)
                    .join(Universe, Universe.id == UniverseMember.universe_id)
                    .where(
                        ETF.market == market,
                        ETF.trade_date == day,
                        Universe.key == f"{market.lower()}_index_etf",
                        Universe.market == market,
                        Universe.enabled.is_(True),
                        # The configured Rotation pool defines eligibility; provider directory types may be coarse.
                        Instrument.market == market,
                        Instrument.listing_status == "ACTIVE",
                    )
                )
                .mappings()
                .all()
            )
            etfs = {row["code"]: dict(row) for row in rows}
        result = []
        for code, linked in memberships.items():
            matched = [
                dict(etfs[key], mapping_reasons=reasons) for key, reasons in sorted(linked.items()) if key in etfs
            ]
            if matched:
                result.append(
                    dict(
                        code=code,
                        trade_date=day,
                        generated_at=max(r["generated_at"] for r in matched),
                        mapping_version=MAPPING_VERSION,
                        etfs=matched,
                    )
                )
        return result

    def macro(self, market, day):
        from datetime import datetime, time
        from zoneinfo import ZoneInfo
        from finance_analysis.database.models.stock import StockDaily
        from finance_analysis.database.models.universe import Universe, UniverseMember
        from finance_analysis.macro.config import MACRO_INSTRUMENTS
        from finance_analysis.macro.models import MacroContext
        from finance_analysis.macro.service import MacroService
        from finance_analysis.market_review.trading_calendar import get_effective_trading_date

        cutoff = datetime.combine(
            day,
            time(20, 30) if market == "CN" else time(23, 30),
            ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York"),
        )
        expected = get_effective_trading_date("us", current_time=cutoff)
        with self.db.get_session() as session:
            members = session.execute(
                select(Instrument.id, Instrument.code, Instrument.name)
                .join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
                .join(Universe, Universe.id == UniverseMember.universe_id)
                .where(Universe.key == "us_macro", Universe.enabled.is_(True), Instrument.code.in_(MACRO_INSTRUMENTS))
            ).all()
            if not members:
                return []
            ranked = (
                select(
                    StockDaily.instrument_id,
                    StockDaily.date,
                    StockDaily.close,
                    func.row_number()
                    .over(partition_by=StockDaily.instrument_id, order_by=StockDaily.date.desc())
                    .label("rn"),
                )
                .where(
                    StockDaily.instrument_id.in_([r.id for r in members]),
                    StockDaily.date <= expected,
                    StockDaily.close > 0,
                    StockDaily.close < float("inf"),
                )
                .subquery()
            )
            rows = session.execute(select(ranked).where(ranked.c.rn <= 21)).mappings().all()
        histories = {r.code: {} for r in members}
        by_id = {r.id: r.code for r in members}
        for r in rows:
            histories[by_id[r["instrument_id"]]][r["date"]] = float(r["close"])
        latest = {code: max(history) for code, history in histories.items() if history}
        # Never move the baseline back when the entire macro universe is stale.
        context = MacroContext(
            {r.code: r.name for r in members},
            latest,
            expected,
            min((d for h in histories.values() for d in h), default=expected),
        )
        result = MacroService.calculate_dashboard(context, histories)
        if result.risk_score is None:
            return []
        return [
            dict(
                trade_date=expected,
                generated_at=result.generated_at,
                risk_score=result.risk_score,
                regime=result.regime,
                states=result.states.model_dump(),
                signal_coverage=result.signal_coverage,
                signals=[r.model_dump() for r in result.signals],
                cutoff=cutoff.isoformat(),
            )
        ]

    def options(self, market, day):
        if market != "US":
            return []
        from finance_analysis.database.models.options_intelligence import OptionDailyMetrics as O

        with self.db.get_session() as session:
            return [
                dict(row)
                for row in session.execute(
                    select(
                        O.symbol.label("code"),
                        O.trade_date,
                        O.created_at.label("generated_at"),
                        O.metrics["scores"].label("scores"),
                        O.metrics["confidence"].label("confidence"),
                        O.metrics["evidence_grade"].label("evidence_grade"),
                    ).where(O.trade_date == day)
                ).mappings()
            ]

    def sentiment(self, market, day):
        if market != "CN":
            return []
        from finance_analysis.database.models.market_sentiment import MarketSentimentSnapshot as S

        with self.db.get_session() as session:
            row = session.get(S, day)
            if row is None:
                return []
            payload = row.payload
            return [
                dict(
                    trade_date=day,
                    generated_at=row.generated_at,
                    state=row.state,
                    **{
                        key: payload.get(key)
                        for key in (
                            "heat_score",
                            "limit_up_count",
                            "multi_board_count",
                            "highest_board",
                            "state_reasons",
                        )
                    },
                )
            ]

    def save(self, market, day, rows, manifest):
        if (manifest.get("algorithm_version") or "").startswith("confluence_v2") and len(rows) > 10:
            raise ValueError("V2 daily shortlist cannot exceed 10 signals per market")
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
                    rules=None,
                    items=[],
                )
            return dict(
                values(rows[0][0], "market trade_date generated_at algorithm_version source_availability rules"),
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
