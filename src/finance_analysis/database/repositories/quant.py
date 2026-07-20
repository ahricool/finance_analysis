"""Transactional repository boundary for quant research data."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import and_, delete, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.quant import (
    DailyFeatureSnapshot, EventFeatureDaily, IntradayConfirmation, MarketEvent, MarketRegimeSnapshot, ModelDefinition, ModelPublication,
    ModelRun, ModelSignal, PortfolioRecommendation, PortfolioRecommendationItem,
    QuantDatasetSnapshot, QuantUniverse, QuantUniverseMember, SectorRegimeSnapshot,
)
from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
from finance_analysis.quant.markets import validate_universe_for_market


class QuantRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager
            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    @staticmethod
    def _detach(session, rows):
        for row in rows:
            session.expunge(row)
        return rows

    def list_universes(self, market: str | None = None, enabled: bool | None = True) -> list[QuantUniverse]:
        clauses = []
        if market:
            clauses.append(QuantUniverse.market == market.upper())
        if enabled is not None:
            clauses.append(QuantUniverse.enabled.is_(enabled))
        with self.db.get_session() as session:
            rows = list(session.execute(select(QuantUniverse).where(*clauses).order_by(QuantUniverse.key)).scalars())
            return self._detach(session, rows)

    def get_universe(self, key_or_id: str | int) -> QuantUniverse | None:
        clause = QuantUniverse.id == key_or_id if isinstance(key_or_id, int) else QuantUniverse.key == key_or_id
        with self.db.get_session() as session:
            row = session.execute(select(QuantUniverse).where(clause)).scalar_one_or_none()
            if row:
                session.expunge(row)
            return row

    def supported_universe(self, market: str, universe_key: str | None = None) -> QuantUniverse:
        """Return the market's single enabled universe or reject the requested key."""
        normalized_market = str(market).upper()
        key = validate_universe_for_market(normalized_market, universe_key)
        row = self.get_universe(key)
        if not row or row.market != normalized_market or not row.enabled:
            raise ValueError(f"Supported {normalized_market} universe {key} is not available")
        return row

    @staticmethod
    def _require_supported_universe_row(session, market: str, universe_id: int) -> QuantUniverse:
        normalized_market = str(market).upper()
        row = session.get(QuantUniverse, universe_id)
        if not row or row.market != normalized_market:
            raise ValueError(f"Universe id={universe_id} is not enabled for market={normalized_market}")
        validate_universe_for_market(normalized_market, row.key)
        if not row.enabled:
            raise ValueError(f"Universe id={universe_id} is not enabled for market={normalized_market}")
        return row

    def upsert_universe(self, values: dict[str, Any]) -> QuantUniverse:
        with self.db.session_scope() as session:
            stmt = pg_insert(QuantUniverse).values(**values).on_conflict_do_update(
                index_elements=[QuantUniverse.key],
                set_={key: value for key, value in values.items() if key != "key"},
            ).returning(QuantUniverse)
            row = session.execute(stmt).scalar_one()
            session.expunge(row)
            return row

    def update_universe(self, universe_id: int, **values: Any) -> None:
        with self.db.session_scope() as session:
            session.execute(update(QuantUniverse).where(QuantUniverse.id == universe_id).values(**values))

    def latest_member_mappings(self, universe_id: int) -> dict[int, dict[str, Any]]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(QuantUniverseMember)
                .where(QuantUniverseMember.universe_id == universe_id)
                .order_by(QuantUniverseMember.symbol_id, desc(QuantUniverseMember.effective_from))
            ).scalars()
            result: dict[int, dict[str, Any]] = {}
            for row in rows:
                result.setdefault(
                    row.symbol_id,
                    {
                        "sector_key": row.sector_key,
                        "sector_benchmark_code": row.sector_benchmark_code,
                        "source": "persisted",
                    },
                )
            return result

    def sync_dynamic_members(
        self,
        universe_id: int,
        symbols: Iterable[MarketDataSymbol],
        mappings: dict[int, dict[str, Any]],
        effective_from: date,
    ) -> dict[str, int]:
        desired = {symbol.id for symbol in symbols}
        added = ended = updated = 0
        with self.db.session_scope() as session:
            active = {
                row.symbol_id: row
                for row in session.execute(
                    select(QuantUniverseMember).where(
                        QuantUniverseMember.universe_id == universe_id,
                        QuantUniverseMember.enabled.is_(True),
                        QuantUniverseMember.effective_to.is_(None),
                    )
                ).scalars()
            }
            for symbol_id, row in active.items():
                if symbol_id not in desired:
                    row.effective_to = max(row.effective_from, effective_from - timedelta(days=1))
                    # Preserve ended periods for historical point-in-time reads.
                    # A member created and removed on the same effective date has
                    # no historical active interval, so disable that one record.
                    row.enabled = row.effective_from < effective_from
                    ended += 1
                    continue
                mapping = mappings.get(symbol_id, {})
                sector_key = mapping.get("sector_key")
                benchmark = mapping.get("sector_benchmark_code")
                if (sector_key and row.sector_key != sector_key) or (benchmark and row.sector_benchmark_code != benchmark):
                    row.sector_key = sector_key
                    row.sector_benchmark_code = benchmark
                    updated += 1
            for symbol_id in sorted(desired - set(active)):
                mapping = mappings.get(symbol_id, {})
                session.add(
                    QuantUniverseMember(
                        universe_id=universe_id,
                        symbol_id=symbol_id,
                        effective_from=effective_from,
                        sector_key=mapping.get("sector_key"),
                        sector_benchmark_code=mapping.get("sector_benchmark_code"),
                        enabled=True,
                    )
                )
                added += 1
        return {"added": added, "ended": ended, "updated": updated}

    def active_members(self, universe_id: int, as_of: date) -> list[tuple[QuantUniverseMember, MarketDataSymbol]]:
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(QuantUniverseMember, MarketDataSymbol)
                .join(MarketDataSymbol, MarketDataSymbol.id == QuantUniverseMember.symbol_id)
                .where(
                    QuantUniverseMember.universe_id == universe_id,
                    QuantUniverseMember.enabled.is_(True),
                    QuantUniverseMember.effective_from <= as_of,
                    or_(QuantUniverseMember.effective_to.is_(None), QuantUniverseMember.effective_to >= as_of),
                ).order_by(MarketDataSymbol.code)
            ).all())
            for member, symbol in rows:
                session.expunge(member); session.expunge(symbol)
            return rows

    def daily_bar_codes(self, codes: set[str], trade_date: date) -> set[str]:
        """Return universe codes with a daily bar on the requested trading date."""
        if not codes:
            return set()
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(MarketDataSymbol.code)
                    .join(StockDaily, StockDaily.symbol_id == MarketDataSymbol.id)
                    .where(MarketDataSymbol.code.in_(codes), StockDaily.date == trade_date)
                ).scalars()
            )

    def create_dataset(self, values: dict[str, Any]) -> QuantDatasetSnapshot:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, values["market"], values["universe_id"])
            row = QuantDatasetSnapshot(**values); session.add(row); session.flush(); session.refresh(row); session.expunge(row)
            return row

    def update_dataset(self, snapshot_id: int, **values: Any) -> None:
        with self.db.session_scope() as session:
            session.execute(update(QuantDatasetSnapshot).where(QuantDatasetSnapshot.id == snapshot_id).values(**values))

    def list_datasets(
        self,
        limit: int = 100,
        market: str | None = None,
        universe_id: int | None = None,
    ) -> list[QuantDatasetSnapshot]:
        clauses = [QuantDatasetSnapshot.market == market.upper()] if market else []
        if universe_id is not None:
            clauses.append(QuantDatasetSnapshot.universe_id == universe_id)
        with self.db.get_session() as session:
            rows = list(session.execute(select(QuantDatasetSnapshot).where(*clauses).order_by(desc(QuantDatasetSnapshot.created_at)).limit(limit)).scalars())
            return self._detach(session, rows)

    def get_dataset(self, snapshot_id: int) -> QuantDatasetSnapshot | None:
        with self.db.get_session() as session:
            row = session.get(QuantDatasetSnapshot, snapshot_id)
            if row: session.expunge(row)
            return row

    def upsert_event(self, values: dict[str, Any]) -> tuple[MarketEvent, bool]:
        with self.db.session_scope() as session:
            existing = session.execute(select(MarketEvent).where(MarketEvent.dedupe_key == values["dedupe_key"])).scalar_one_or_none()
            if existing:
                session.expunge(existing); return existing, False
            row = MarketEvent(**values); session.add(row); session.flush(); session.refresh(row); session.expunge(row)
            return row, True

    def list_events(self, filters: dict[str, Any], offset: int = 0, limit: int = 100) -> tuple[list[MarketEvent], int]:
        clauses = []
        for key in ("market", "code", "event_type", "direction", "source"):
            if filters.get(key): clauses.append(getattr(MarketEvent, key) == filters[key])
        if filters.get("published_from"): clauses.append(MarketEvent.published_at >= filters["published_from"])
        if filters.get("published_to"): clauses.append(MarketEvent.published_at <= filters["published_to"])
        with self.db.get_session() as session:
            total = session.execute(select(func.count(MarketEvent.id)).where(*clauses)).scalar_one()
            rows = list(session.execute(select(MarketEvent).where(*clauses).order_by(desc(MarketEvent.published_at)).offset(offset).limit(limit)).scalars())
            return self._detach(session, rows), total

    def get_event(self, event_id: int) -> MarketEvent | None:
        with self.db.get_session() as session:
            row = session.get(MarketEvent, event_id)
            if row: session.expunge(row)
            return row

    def available_events(self, symbol_id: int, cutoff: datetime, since: datetime) -> list[MarketEvent]:
        with self.db.get_session() as session:
            rows = list(session.execute(select(MarketEvent).where(
                MarketEvent.symbol_id == symbol_id, MarketEvent.available_at <= cutoff, MarketEvent.available_at >= since
            ).order_by(MarketEvent.available_at)).scalars())
            return self._detach(session, rows)

    def upsert_daily_features(self, model, constraint: str, values: list[dict[str, Any]], key_fields: set[str]) -> None:
        with self.db.session_scope() as session:
            for value in values:
                session.execute(pg_insert(model).values(**value).on_conflict_do_update(
                    constraint=constraint, set_={key: val for key, val in value.items() if key not in key_fields}
                ))

    def save_daily_features(self, values: list[dict[str, Any]]) -> None:
        self.upsert_daily_features(DailyFeatureSnapshot, "uix_daily_feature_snapshot", values, {"trade_date", "symbol_id", "feature_version"})

    def save_event_features(self, values: list[dict[str, Any]]) -> None:
        self.upsert_daily_features(EventFeatureDaily, "uix_event_feature_daily", values, {"trade_date", "symbol_id", "feature_version"})

    def feature_context(self, trade_date: date, feature_version: str, event_feature_version: str) -> dict[int, dict[str, Any]]:
        with self.db.get_session() as session:
            rows=session.execute(select(DailyFeatureSnapshot,EventFeatureDaily).join(EventFeatureDaily,and_(
                EventFeatureDaily.trade_date==DailyFeatureSnapshot.trade_date,EventFeatureDaily.symbol_id==DailyFeatureSnapshot.symbol_id
            )).where(DailyFeatureSnapshot.trade_date==trade_date,DailyFeatureSnapshot.feature_version==feature_version,
                      EventFeatureDaily.feature_version==event_feature_version)).all()
            result = {}
            for daily, event in rows:
                features = daily.features or {}
                result[daily.symbol_id] = {
                    "sector_score": daily.sector_score,
                    "event_score": event.event_score,
                    "negative_event_veto": event.negative_event_veto,
                    "event_payload": event.feature_payload,
                    "sector_key": features.get("sector_key"),
                    "has_sufficient_data": features.get("has_sufficient_data"),
                    "liquidity": features.get("liquidity"),
                    "risk_penalty": features.get("risk_penalty"),
                    "close": features.get("close"),
                }
            return result

    def save_market_regime(self, values: dict[str, Any]) -> MarketRegimeSnapshot:
        with self.db.session_scope() as session:
            stmt = pg_insert(MarketRegimeSnapshot).values(**values).on_conflict_do_update(
                constraint="uix_market_regime_version", set_={key: value for key, value in values.items() if key not in {"market", "trade_date", "model_version"}}
            ).returning(MarketRegimeSnapshot)
            row = session.execute(stmt).scalar_one(); session.expunge(row); return row

    def market_regimes(self, market: str, date_from: date | None = None, date_to: date | None = None, limit: int = 365) -> list[MarketRegimeSnapshot]:
        clauses = [MarketRegimeSnapshot.market == market]
        if date_from: clauses.append(MarketRegimeSnapshot.trade_date >= date_from)
        if date_to: clauses.append(MarketRegimeSnapshot.trade_date <= date_to)
        with self.db.get_session() as session:
            rows = list(session.execute(select(MarketRegimeSnapshot).where(*clauses).order_by(desc(MarketRegimeSnapshot.trade_date)).limit(limit)).scalars())
            return self._detach(session, rows)

    def save_sector_regimes(self, values: Iterable[dict[str, Any]]) -> None:
        with self.db.session_scope() as session:
            for value in values:
                session.execute(pg_insert(SectorRegimeSnapshot).values(**value).on_conflict_do_update(
                    constraint="uix_sector_regime_version", set_={k: v for k, v in value.items() if k not in {"market", "trade_date", "sector_key", "model_version"}}
                ))

    def sector_regimes(self, market: str, trade_date: date | None = None, sector_key: str | None = None) -> list[SectorRegimeSnapshot]:
        clauses = [SectorRegimeSnapshot.market == market]
        if trade_date:
            clauses.append(SectorRegimeSnapshot.trade_date == trade_date)
        else:
            latest_date = select(func.max(SectorRegimeSnapshot.trade_date)).where(
                SectorRegimeSnapshot.market == market
            ).scalar_subquery()
            clauses.append(SectorRegimeSnapshot.trade_date == latest_date)
        if sector_key: clauses.append(SectorRegimeSnapshot.sector_key == sector_key)
        with self.db.get_session() as session:
            rows = list(session.execute(select(SectorRegimeSnapshot).where(*clauses).order_by(desc(SectorRegimeSnapshot.trade_date), SectorRegimeSnapshot.rank)).scalars())
            return self._detach(session, rows)

    def list_model_definitions(self) -> list[ModelDefinition]:
        with self.db.get_session() as session:
            rows = list(session.execute(select(ModelDefinition).order_by(ModelDefinition.key)).scalars())
            return self._detach(session, rows)

    def get_model_definition(self, key: str) -> ModelDefinition | None:
        with self.db.get_session() as session:
            row = session.execute(select(ModelDefinition).where(ModelDefinition.key == key)).scalar_one_or_none()
            if row: session.expunge(row)
            return row

    def create_model_run(self, values: dict[str, Any]) -> ModelRun:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, values["market"], values["universe_id"])
            row = ModelRun(**values); session.add(row); session.flush(); session.refresh(row); session.expunge(row); return row

    def update_model_run(self, run_id: int, **values: Any) -> None:
        with self.db.session_scope() as session:
            run = session.get(ModelRun, run_id)
            if not run:
                raise ValueError(f"Unknown model run {run_id}")
            self._require_supported_universe_row(session, run.market, run.universe_id)
            session.execute(update(ModelRun).where(ModelRun.id == run_id).values(**values))

    def get_model_run(self, run_id: int) -> ModelRun | None:
        with self.db.get_session() as session:
            row = session.get(ModelRun, run_id)
            if row: session.expunge(row)
            return row

    def list_model_runs(
        self,
        limit: int = 100,
        market: str | None = None,
        universe_id: int | None = None,
    ) -> list[ModelRun]:
        clauses = [ModelRun.market == market.upper()] if market else []
        if universe_id is not None:
            clauses.append(ModelRun.universe_id == universe_id)
        with self.db.get_session() as session:
            rows = list(session.execute(select(ModelRun).where(*clauses).order_by(desc(ModelRun.created_at)).limit(limit)).scalars())
            return self._detach(session, rows)

    def publish_model(self, run_id: int, user_id: int, reason: str) -> ModelRun:
        with self.db.session_scope() as session:
            run = session.execute(select(ModelRun).where(ModelRun.id == run_id).with_for_update()).scalar_one()
            self._require_supported_universe_row(session, run.market, run.universe_id)
            if run.status != "candidate": raise ValueError("Only candidate models can be published")
            previous = session.execute(select(ModelRun).where(
                ModelRun.market == run.market, ModelRun.model_key == run.model_key, ModelRun.status == "production"
            ).with_for_update()).scalar_one_or_none()
            if previous: previous.status = "retired"
            run.status = "production"
            session.add(ModelPublication(model_run_id=run.id, previous_model_run_id=previous.id if previous else None, published_by=user_id, reason=reason))
            session.flush(); session.refresh(run); session.expunge(run); return run

    def production_model(self, market: str, model_key: str) -> ModelRun | None:
        expected_universe = validate_universe_for_market(market)
        with self.db.get_session() as session:
            row = session.execute(
                select(ModelRun)
                .join(QuantUniverse, QuantUniverse.id == ModelRun.universe_id)
                .where(
                    ModelRun.market == market.upper(),
                    ModelRun.model_key == model_key,
                    ModelRun.status == "production",
                    QuantUniverse.market == market.upper(),
                    QuantUniverse.key == expected_universe,
                    QuantUniverse.enabled.is_(True),
                )
                .order_by(desc(ModelRun.finished_at))
            ).scalar_one_or_none()
            if row: session.expunge(row)
            return row

    def replace_signals(self, market: str, universe_id: int, trade_date: date, model_version: str, values: list[dict[str, Any]]) -> None:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, market, universe_id)
            session.execute(delete(ModelSignal).where(
                ModelSignal.market == market,
                ModelSignal.universe_id == universe_id,
                ModelSignal.trade_date == trade_date,
                ModelSignal.model_version == model_version,
            ))
            if values: session.add_all(ModelSignal(**value) for value in values)

    def save_portfolio(self, values: dict[str, Any], items: list[dict[str, Any]]) -> PortfolioRecommendation:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, values["market"], values["universe_id"])
            existing = session.execute(select(PortfolioRecommendation).where(
                PortfolioRecommendation.trade_date == values["trade_date"], PortfolioRecommendation.universe_id == values["universe_id"],
                PortfolioRecommendation.model_version == values["model_version"])).scalar_one_or_none()
            if existing:
                session.execute(delete(PortfolioRecommendationItem).where(PortfolioRecommendationItem.recommendation_id == existing.id))
                for key, value in values.items(): setattr(existing, key, value)
                row = existing
            else:
                row = PortfolioRecommendation(**values); session.add(row); session.flush()
            session.add_all(PortfolioRecommendationItem(recommendation_id=row.id, **item) for item in items)
            session.flush(); session.refresh(row); session.expunge(row); return row

    def save_confirmations(self, values: list[dict[str, Any]]) -> None:
        with self.db.session_scope() as session:
            if not values:
                return
            item_ids = {value["recommendation_item_id"] for value in values}
            universes = list(
                session.execute(
                    select(QuantUniverse)
                    .join(
                        PortfolioRecommendation,
                        PortfolioRecommendation.universe_id == QuantUniverse.id,
                    )
                    .join(
                        PortfolioRecommendationItem,
                        PortfolioRecommendationItem.recommendation_id == PortfolioRecommendation.id,
                    )
                    .where(PortfolioRecommendationItem.id.in_(item_ids))
                    .distinct()
                ).scalars()
            )
            if not universes:
                raise ValueError("Intraday confirmations require supported portfolio items")
            for universe in universes:
                validate_universe_for_market(universe.market, universe.key)
                if not universe.enabled:
                    raise ValueError(f"Universe {universe.key} is not enabled")
            session.add_all(IntradayConfirmation(**value) for value in values)

    def latest_signals(self, market: str, universe_id: int | None = None, code: str | None = None, limit: int = 200) -> list[ModelSignal]:
        scope = [ModelSignal.market == market]
        if universe_id:
            scope.append(ModelSignal.universe_id == universe_id)
        if code:
            scope.append(ModelSignal.code == code.upper())
        latest_date = select(func.max(ModelSignal.trade_date)).where(*scope).scalar_subquery()
        clauses = [*scope, ModelSignal.trade_date == latest_date]
        with self.db.get_session() as session:
            rows = list(session.execute(select(ModelSignal).where(*clauses).order_by(ModelSignal.universe_rank).limit(limit)).scalars())
            return self._detach(session, rows)

    def signal_history(
        self,
        market: str,
        code: str,
        universe_id: int | None = None,
        limit: int = 365,
    ) -> list[ModelSignal]:
        clauses = [ModelSignal.market == market.upper(), ModelSignal.code == code.upper()]
        if universe_id is not None:
            clauses.append(ModelSignal.universe_id == universe_id)
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(ModelSignal).where(*clauses).order_by(desc(ModelSignal.trade_date)).limit(limit)
            ).scalars())
            return self._detach(session, rows)

    def latest_portfolios(self, market: str, universe_id: int | None = None, limit: int = 50) -> list[PortfolioRecommendation]:
        clauses = [PortfolioRecommendation.market == market]
        if universe_id: clauses.append(PortfolioRecommendation.universe_id == universe_id)
        with self.db.get_session() as session:
            rows = list(session.execute(select(PortfolioRecommendation).where(*clauses).order_by(desc(PortfolioRecommendation.trade_date)).limit(limit)).scalars())
            return self._detach(session, rows)

    def portfolio(
        self,
        recommendation_id: int,
        market: str | None = None,
        universe_id: int | None = None,
    ) -> tuple[PortfolioRecommendation, list[PortfolioRecommendationItem]] | None:
        with self.db.get_session() as session:
            row = session.get(PortfolioRecommendation, recommendation_id)
            if (
                not row
                or (market and row.market != market.upper())
                or (universe_id is not None and row.universe_id != universe_id)
            ):
                return None
            items = list(session.execute(select(PortfolioRecommendationItem).where(PortfolioRecommendationItem.recommendation_id == row.id).order_by(PortfolioRecommendationItem.rank)).scalars())
            session.expunge(row); self._detach(session, items); return row, items

    def confirmations(
        self,
        market: str,
        trade_date: date | None = None,
        code: str | None = None,
        universe_id: int | None = None,
        limit: int = 200,
    ) -> list[IntradayConfirmation]:
        clauses = []
        if trade_date: clauses.append(IntradayConfirmation.trade_date == trade_date)
        if code: clauses.append(IntradayConfirmation.code == code.upper())
        with self.db.get_session() as session:
            rows = list(session.execute(
                select(IntradayConfirmation)
                .join(PortfolioRecommendationItem, PortfolioRecommendationItem.id == IntradayConfirmation.recommendation_item_id)
                .join(PortfolioRecommendation, PortfolioRecommendation.id == PortfolioRecommendationItem.recommendation_id)
                .where(
                    PortfolioRecommendation.market == market.upper(),
                    *(
                        [PortfolioRecommendation.universe_id == universe_id]
                        if universe_id is not None
                        else []
                    ),
                    *clauses,
                )
                .order_by(desc(IntradayConfirmation.evaluated_at)).limit(limit)
            ).scalars())
            return self._detach(session, rows)


__all__ = ["QuantRepository"]
