"""Transactional repository boundary for quant research data."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy import and_, case, delete, desc, func, or_, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.quant import (
    MarketRegimeSnapshot,
    ModelDefinition,
    ModelPublication,
    ModelRun,
    ModelSignal,
    PortfolioRecommendation,
    PortfolioRecommendationItem,
    QuantDatasetSnapshot,
    QuantExecution,
    QuantModelRelease,
)
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.models.universe import Universe
from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES, validate_universe_for_market


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

    def names_by_codes(self, codes: Iterable[str]) -> dict[str, str]:
        """Read persisted instrument names in one query for API payload enrichment."""
        canonical_codes = sorted({str(code or "").strip().upper() for code in codes if str(code or "").strip()})
        if not canonical_codes:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(Instrument.code, Instrument.name).where(Instrument.code.in_(canonical_codes))
            ).all()
        return {str(code): str(name).strip() for code, name in rows if str(name or "").strip()}

    def list_universes(self, market: str | None = None, enabled: bool | None = True) -> list[Universe]:
        clauses = [Universe.key.in_(tuple(DEFAULT_QUANT_UNIVERSES.values()))]
        if market:
            clauses.append(Universe.market == market.upper())
        if enabled is not None:
            clauses.append(Universe.enabled.is_(enabled))
        with self.db.get_session() as session:
            rows = list(session.execute(select(Universe).where(*clauses).order_by(Universe.key)).scalars())
            return self._detach(session, rows)

    def get_universe(self, key_or_id: str | int) -> Universe | None:
        clause = Universe.id == key_or_id if isinstance(key_or_id, int) else Universe.key == key_or_id
        with self.db.get_session() as session:
            row = session.execute(select(Universe).where(clause)).scalar_one_or_none()
            if row:
                session.expunge(row)
            return row

    def supported_universe(self, market: str, universe_key: str | None = None) -> Universe:
        """Return the market's single enabled universe or reject the requested key."""
        normalized_market = str(market).upper()
        key = validate_universe_for_market(normalized_market, universe_key)
        row = self.get_universe(key)
        if not row or row.market != normalized_market or not row.enabled:
            raise ValueError(f"Supported {normalized_market} universe {key} is not available")
        return row

    @staticmethod
    def _require_supported_universe_row(session, market: str, universe_id: int) -> Universe:
        normalized_market = str(market).upper()
        row = session.get(Universe, universe_id)
        if not row or row.market != normalized_market:
            raise ValueError(f"Universe id={universe_id} is not enabled for market={normalized_market}")
        validate_universe_for_market(normalized_market, row.key)
        if not row.enabled:
            raise ValueError(f"Universe id={universe_id} is not enabled for market={normalized_market}")
        return row

    def daily_bar_codes(self, codes: set[str], trade_date: date) -> set[str]:
        """Return universe codes with a daily bar on the requested trading date."""
        if not codes:
            return set()
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(Instrument.code)
                    .join(StockDaily, StockDaily.instrument_id == Instrument.id)
                    .where(Instrument.code.in_(codes), StockDaily.date == trade_date)
                ).scalars()
            )

    def load_daily_bar_rows(
        self,
        market: str,
        codes: set[str],
        start: date,
        end: date,
    ) -> list[Any]:
        """Load canonical forward-adjusted daily bars."""
        if not codes:
            return []
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(
                        Instrument.code.label("instrument"),
                        StockDaily.date.label("datetime"),
                        StockDaily.open,
                        StockDaily.high,
                        StockDaily.low,
                        StockDaily.close,
                        StockDaily.volume,
                        StockDaily.amount,
                        StockDaily.data_source.label("daily_data_source"),
                    )
                    .join(StockDaily, StockDaily.instrument_id == Instrument.id)
                    .where(
                        Instrument.market == market.upper(),
                        Instrument.code.in_(codes),
                        StockDaily.date.between(start, end),
                    )
                    .order_by(Instrument.code, StockDaily.date)
                ).mappings()
            )

    def load_return_daily_rows(self, codes: set[str], signal_date: date | None) -> list[Any]:
        """Read T0..T5 and the latest valid close for all requested symbols in one query."""
        if not codes or signal_date is None:
            return []
        latest_valid_date = func.max(
            case((and_(StockDaily.close > 0, StockDaily.close < float("inf")), StockDaily.date))
        ).over(partition_by=StockDaily.instrument_id)
        ranked = (
            select(
                Instrument.code,
                StockDaily.date,
                StockDaily.close,
                func.row_number()
                .over(partition_by=StockDaily.instrument_id, order_by=StockDaily.date)
                .label("ordinal"),
                latest_valid_date.label("latest_valid_date"),
            )
            .join(StockDaily, StockDaily.instrument_id == Instrument.id)
            .where(Instrument.code.in_(codes), StockDaily.date >= signal_date)
            .subquery()
        )
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(ranked)
                    .where(or_(ranked.c.ordinal <= 6, ranked.c.date == ranked.c.latest_valid_date))
                    .order_by(ranked.c.code, ranked.c.date)
                ).mappings()
            )

    def create_dataset(self, values: dict[str, Any]) -> QuantDatasetSnapshot:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, values["market"], values["universe_id"])
            row = QuantDatasetSnapshot(**values)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
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
            rows = list(
                session.execute(
                    select(QuantDatasetSnapshot)
                    .where(*clauses)
                    .order_by(desc(QuantDatasetSnapshot.created_at))
                    .limit(limit)
                ).scalars()
            )
            return self._detach(session, rows)

    def get_dataset(self, snapshot_id: int) -> QuantDatasetSnapshot | None:
        with self.db.get_session() as session:
            row = session.get(QuantDatasetSnapshot, snapshot_id)
            if row:
                session.expunge(row)
            return row

    def get_dataset_by_key(self, dataset_key: str) -> QuantDatasetSnapshot | None:
        with self.db.get_session() as session:
            row = session.execute(
                select(QuantDatasetSnapshot).where(QuantDatasetSnapshot.dataset_key == dataset_key)
            ).scalar_one_or_none()
            if row:
                session.expunge(row)
            return row

    def delete_dataset(self, snapshot_id: int, market: str, universe_id: int) -> dict[str, Any] | None:
        """Delete an idle dataset that is not referenced by any model run."""
        with self.db.session_scope() as session:
            row = session.execute(
                select(QuantDatasetSnapshot)
                .where(
                    QuantDatasetSnapshot.id == snapshot_id,
                    QuantDatasetSnapshot.market == market.upper(),
                    QuantDatasetSnapshot.universe_id == universe_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if not row:
                return None
            if row.status in {"pending", "building"}:
                raise ValueError("A pending or building dataset cannot be deleted")
            referenced_run_id = session.execute(
                select(ModelRun.id).where(ModelRun.dataset_snapshot_id == snapshot_id).limit(1)
            ).scalar_one_or_none()
            if referenced_run_id is not None:
                raise ValueError(f"Dataset is referenced by model run {referenced_run_id}; delete its model runs first")
            result = {"id": row.id, "artifact_uri": row.artifact_uri}
            session.delete(row)
            session.flush()
            return result

    def save_market_regime(self, values: dict[str, Any]) -> MarketRegimeSnapshot:
        with self.db.session_scope() as session:
            stmt = (
                pg_insert(MarketRegimeSnapshot)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uix_market_regime_version",
                    set_={
                        key: value
                        for key, value in values.items()
                        if key not in {"market", "trade_date", "model_version"}
                    },
                )
                .returning(MarketRegimeSnapshot)
            )
            row = session.execute(stmt).scalar_one()
            session.expunge(row)
            return row

    def market_regimes(
        self,
        market: str,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 365,
        model_version: str | None = None,
    ) -> list[MarketRegimeSnapshot]:
        clauses = [MarketRegimeSnapshot.market == market]
        if date_from:
            clauses.append(MarketRegimeSnapshot.trade_date >= date_from)
        if date_to:
            clauses.append(MarketRegimeSnapshot.trade_date <= date_to)
        if model_version:
            clauses.append(MarketRegimeSnapshot.model_version == model_version)
        with self.db.get_session() as session:
            ranked = (
                select(
                    MarketRegimeSnapshot.id.label("snapshot_id"),
                    func.row_number()
                    .over(
                        partition_by=MarketRegimeSnapshot.trade_date,
                        order_by=(
                            desc(MarketRegimeSnapshot.generated_at),
                            desc(MarketRegimeSnapshot.id),
                        ),
                    )
                    .label("version_rank"),
                )
                .where(*clauses)
                .subquery()
            )
            rows = list(
                session.execute(
                    select(MarketRegimeSnapshot)
                    .join(ranked, ranked.c.snapshot_id == MarketRegimeSnapshot.id)
                    .where(ranked.c.version_rank == 1)
                    .order_by(desc(MarketRegimeSnapshot.trade_date))
                    .limit(limit)
                ).scalars()
            )
            return self._detach(session, rows)

    def list_model_definitions(self) -> list[ModelDefinition]:
        with self.db.get_session() as session:
            rows = list(session.execute(select(ModelDefinition).order_by(ModelDefinition.key)).scalars())
            return self._detach(session, rows)

    def get_model_definition(self, key: str) -> ModelDefinition | None:
        with self.db.get_session() as session:
            row = session.execute(select(ModelDefinition).where(ModelDefinition.key == key)).scalar_one_or_none()
            if row:
                session.expunge(row)
            return row

    def create_model_run(self, values: dict[str, Any]) -> ModelRun:
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, values["market"], values["universe_id"])
            row = ModelRun(**values)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def update_model_run(self, run_id: int, *, expected_statuses: set[str] | None = None, **values: Any) -> bool:
        with self.db.session_scope() as session:
            run = session.get(ModelRun, run_id, with_for_update=True)
            if not run:
                raise ValueError(f"Unknown model run {run_id}")
            self._require_supported_universe_row(session, run.market, run.universe_id)
            if expected_statuses is not None and run.status not in expected_statuses:
                return False
            session.execute(update(ModelRun).where(ModelRun.id == run_id).values(**values))
            return True

    def get_model_run(self, run_id: int) -> ModelRun | None:
        with self.db.get_session() as session:
            row = session.get(ModelRun, run_id)
            if row:
                session.expunge(row)
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
            rows = list(
                session.execute(
                    select(ModelRun).where(*clauses).order_by(desc(ModelRun.created_at)).limit(limit)
                ).scalars()
            )
            return self._detach(session, rows)

    def delete_model_run(self, run_id: int, market: str, universe_id: int) -> dict[str, Any] | None:
        """Delete a non-running, non-production model run and its dependent rows."""
        with self.db.session_scope() as session:
            row = session.execute(
                select(ModelRun)
                .where(
                    ModelRun.id == run_id,
                    ModelRun.market == market.upper(),
                    ModelRun.universe_id == universe_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if not row:
                return None
            if row.status in {"draft", "training"}:
                raise ValueError("A draft or training model run cannot be deleted")
            if row.status == "production":
                raise ValueError("A production model run cannot be deleted")
            referenced = session.scalar(select(QuantModelRelease.id).where(
                (QuantModelRelease.cross_section_id == run_id) | (QuantModelRelease.time_series_id == run_id)).limit(1))
            if referenced is not None:
                raise ValueError("A model referenced by a release cannot be deleted")
            result = {"id": row.id, "artifact_uri": row.artifact_uri}
            session.execute(delete(ModelPublication).where(ModelPublication.model_run_id == run_id))
            session.delete(row)
            session.flush()
            return result

    def publish_model(self, run_id: int, user_id: int, reason: str) -> ModelRun:
        with self.db.session_scope() as session:
            run = session.execute(select(ModelRun).where(ModelRun.id == run_id).with_for_update()).scalar_one()
            self._require_supported_universe_row(session, run.market, run.universe_id)
            if run.status != "candidate":
                raise ValueError("Only candidate models can be published")
            previous = session.execute(
                select(ModelRun)
                .where(
                    ModelRun.market == run.market, ModelRun.model_key == run.model_key, ModelRun.status == "production"
                )
                .with_for_update()
            ).scalar_one_or_none()
            if previous:
                previous.status = "retired"
            run.status = "production"
            session.add(
                ModelPublication(
                    model_run_id=run.id,
                    previous_model_run_id=previous.id if previous else None,
                    published_by=user_id,
                    reason=reason,
                )
            )
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def production_model(self, market: str, model_key: str) -> ModelRun | None:
        expected_universe = validate_universe_for_market(market)
        with self.db.get_session() as session:
            row = session.execute(
                select(ModelRun)
                .join(Universe, Universe.id == ModelRun.universe_id)
                .where(
                    ModelRun.market == market.upper(),
                    ModelRun.model_key == model_key,
                    ModelRun.status == "production",
                    Universe.market == market.upper(),
                    Universe.key == expected_universe,
                    Universe.enabled.is_(True),
                )
                .order_by(desc(ModelRun.finished_at))
            ).scalar_one_or_none()
            if row:
                session.expunge(row)
            return row

    def replace_signals_and_save_portfolio(
        self,
        market: str,
        universe_id: int,
        trade_date: date,
        model_version: str,
        signals: list[dict[str, Any]],
        portfolio_values: dict[str, Any],
        portfolio_items: list[dict[str, Any]],
        *,
        regime_values: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> PortfolioRecommendation:
        """Atomically publish one daily signal set and its portfolio recommendation."""
        with self.db.session_scope() as session:
            execution = None
            if execution_id:
                execution = session.get(QuantExecution, execution_id, with_for_update=True)
                if execution is None or execution.status not in {"preparing", "predicting", "complete"}:
                    raise ValueError("Execution is no longer eligible for publication")
                if model_version != f"batch-{execution_id}":
                    raise ValueError("Execution batch version mismatch")
                if (execution.market, execution.trade_date, execution.universe_id) != (market, trade_date, universe_id):
                    raise ValueError("Execution scope mismatch")
                if execution.status == "complete":
                    row = session.scalar(select(PortfolioRecommendation).where(
                        PortfolioRecommendation.market == market,
                        PortfolioRecommendation.model_version == model_version))
                    session.expunge(row)
                    return row
                if (execution.market, execution.trade_date, execution.universe_id) != (market, trade_date, universe_id):
                    raise ValueError("Execution scope mismatch")
            self._require_supported_universe_row(session, market, universe_id)
            if regime_values is not None:
                regime = MarketRegimeSnapshot(**regime_values)
                session.add(regime)
                session.flush()
                portfolio_values = {**portfolio_values, "market_regime_id": regime.id}
            if (
                portfolio_values["market"] != market
                or portfolio_values["universe_id"] != universe_id
                or portfolio_values["trade_date"] != trade_date
                or portfolio_values["model_version"] != model_version
            ):
                raise ValueError("Signal and portfolio publication scopes must match")
            session.execute(
                delete(ModelSignal).where(
                    ModelSignal.market == market,
                    ModelSignal.universe_id == universe_id,
                    ModelSignal.trade_date == trade_date,
                    ModelSignal.model_version == model_version,
                )
            )
            if signals:
                session.add_all(ModelSignal(**value) for value in signals)
            existing = session.execute(
                select(PortfolioRecommendation).where(
                    PortfolioRecommendation.trade_date == trade_date,
                    PortfolioRecommendation.universe_id == universe_id,
                    PortfolioRecommendation.model_version == model_version,
                )
            ).scalar_one_or_none()
            if existing:
                session.execute(
                    delete(PortfolioRecommendationItem).where(
                        PortfolioRecommendationItem.recommendation_id == existing.id
                    )
                )
                for key, value in portfolio_values.items():
                    setattr(existing, key, value)
                row = existing
            else:
                row = PortfolioRecommendation(**portfolio_values)
                session.add(row)
                session.flush()
            session.add_all(PortfolioRecommendationItem(recommendation_id=row.id, **item) for item in portfolio_items)
            session.flush()
            session.refresh(row)
            if execution is not None:
                execution.status = "complete"
                execution.finished_at = utc_now()
                execution.summary = {"portfolio_id": row.id}
            session.expunge(row)
            return row

    def available_trade_dates(
        self, market: str, universe_id: int, scope: str = "dashboard", code: str | None = None
    ) -> list[date]:
        """List persisted dates for the requested view, without a history limit."""
        queries = []
        if scope in {"dashboard", "signals"}:
            query = select(ModelSignal.trade_date).where(
                ModelSignal.market == market, ModelSignal.universe_id == universe_id
            )
            if scope == "signals" and code:
                query = query.where(ModelSignal.code == code)
            queries.append(query)
        if scope == "dashboard":
            queries.append(select(MarketRegimeSnapshot.trade_date).where(MarketRegimeSnapshot.market == market))
        if scope == "portfolios":
            queries.append(
                select(PortfolioRecommendation.trade_date).where(
                    PortfolioRecommendation.market == market, PortfolioRecommendation.universe_id == universe_id
                )
            )
        if not queries:
            raise ValueError(f"Unknown quant date scope: {scope}")
        dates = union(*queries).subquery()
        with self.db.get_session() as session:
            return list(session.scalars(select(dates.c.trade_date).distinct().order_by(dates.c.trade_date.desc())))

    def latest_signals(
        self,
        market: str,
        universe_id: int | None = None,
        code: str | None = None,
        limit: int | None = None,
        model_version: str | None = None,
        trade_date: date | None = None,
    ) -> list[ModelSignal]:
        scope = [ModelSignal.market == market]
        if trade_date is not None:
            scope.append(ModelSignal.trade_date == trade_date)
        if universe_id:
            scope.append(ModelSignal.universe_id == universe_id)
        if code:
            scope.append(ModelSignal.code == code.upper())
        if model_version:
            scope.append(ModelSignal.model_version == model_version)
        with self.db.get_session() as session:
            selected = session.execute(
                select(ModelSignal.trade_date, ModelSignal.model_version)
                .where(*scope)
                .order_by(
                    desc(ModelSignal.trade_date),
                    desc(ModelSignal.generated_at),
                    desc(ModelSignal.id),
                )
                .limit(1)
            ).first()
            if selected is None:
                return []
            rows = list(
                session.execute(
                    select(ModelSignal)
                    .where(
                        *scope,
                        ModelSignal.trade_date == selected.trade_date,
                        ModelSignal.model_version == selected.model_version,
                    )
                    .order_by(ModelSignal.universe_rank, ModelSignal.code)
                    .limit(limit)
                ).scalars()
            )
            return self._detach(session, rows)

    def signal_history(
        self,
        market: str,
        code: str,
        universe_id: int | None = None,
        limit: int = 365,
        model_version: str | None = None,
        date_to: date | None = None,
    ) -> list[ModelSignal]:
        clauses = [ModelSignal.market == market.upper(), ModelSignal.code == code.upper()]
        if date_to is not None:
            clauses.append(ModelSignal.trade_date <= date_to)
        if universe_id is not None:
            clauses.append(ModelSignal.universe_id == universe_id)
        if model_version:
            clauses.append(ModelSignal.model_version == model_version)
        with self.db.get_session() as session:
            ranked = (
                select(
                    ModelSignal.id.label("signal_id"),
                    func.row_number()
                    .over(
                        partition_by=ModelSignal.trade_date,
                        order_by=(desc(ModelSignal.generated_at), desc(ModelSignal.id)),
                    )
                    .label("version_rank"),
                )
                .where(*clauses)
                .subquery()
            )
            rows = list(
                session.execute(
                    select(ModelSignal)
                    .join(ranked, ranked.c.signal_id == ModelSignal.id)
                    .where(ranked.c.version_rank == 1)
                    .order_by(desc(ModelSignal.trade_date))
                    .limit(limit)
                ).scalars()
            )
            return self._detach(session, rows)

    def signal_rank_totals(self, rows) -> dict[tuple, int]:
        """Batch denominators for the exact persisted date/universe/model of each signal."""
        scopes = {(row.market, row.universe_id, row.trade_date, row.model_version) for row in rows}
        if not scopes:
            return {}
        fields = (ModelSignal.market, ModelSignal.universe_id, ModelSignal.trade_date, ModelSignal.model_version)
        with self.db.get_session() as session:
            result = session.execute(
                select(*fields, func.count()).where(
                    or_(*(and_(*(field == value for field, value in zip(fields, scope))) for scope in scopes)),
                    ModelSignal.universe_rank > 0,
                ).group_by(*fields)
            ).all()
            return {tuple(row[:4]): row[4] for row in result}

    def latest_portfolios(
        self,
        market: str,
        universe_id: int | None = None,
        limit: int = 50,
        model_version: str | None = None,
        trade_date: date | None = None,
    ) -> list[PortfolioRecommendation]:
        clauses = [PortfolioRecommendation.market == market]
        if trade_date is not None:
            clauses.append(PortfolioRecommendation.trade_date == trade_date)
        if universe_id:
            clauses.append(PortfolioRecommendation.universe_id == universe_id)
        if model_version:
            clauses.append(PortfolioRecommendation.model_version == model_version)
        with self.db.get_session() as session:
            ranked = (
                select(
                    PortfolioRecommendation.id.label("recommendation_id"),
                    func.row_number()
                    .over(
                        partition_by=PortfolioRecommendation.trade_date,
                        order_by=(
                            desc(PortfolioRecommendation.generated_at),
                            desc(PortfolioRecommendation.id),
                        ),
                    )
                    .label("version_rank"),
                )
                .where(*clauses)
                .subquery()
            )
            rows = list(
                session.execute(
                    select(PortfolioRecommendation)
                    .join(ranked, ranked.c.recommendation_id == PortfolioRecommendation.id)
                    .where(ranked.c.version_rank == 1)
                    .order_by(desc(PortfolioRecommendation.trade_date))
                    .limit(limit)
                ).scalars()
            )
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
            items = list(
                session.execute(
                    select(PortfolioRecommendationItem)
                    .where(PortfolioRecommendationItem.recommendation_id == row.id)
                    .order_by(PortfolioRecommendationItem.rank)
                ).scalars()
            )
            session.expunge(row)
            self._detach(session, items)
            return row, items



    def create_execution(self, values):
        from sqlalchemy.exc import IntegrityError
        try:
            with self.db.session_scope() as session:
                row = QuantExecution(**values)
                session.add(row)
                session.flush()
                session.expunge(row)
                return row
        except IntegrityError as exc:
            raise ValueError("This market/date already has an active quant task") from exc

    def update_execution(self, execution_id, **values):
        with self.db.session_scope() as session:
            row = session.get(QuantExecution, execution_id, with_for_update=True)
            if row is not None and row.status not in {"complete", "failed"}:
                for key, value in values.items():
                    setattr(row, key, value)

    def execution(self, execution_id):
        with self.db.get_session() as session:
            row = session.get(QuantExecution, execution_id)
            if row is not None:
                session.expunge(row)
            return row

    def executions(self, market, limit=20):
        with self.db.get_session() as session:
            return self._detach(session, list(session.scalars(select(QuantExecution).where(
                QuantExecution.market == market).order_by(QuantExecution.created_at.desc()).limit(limit))))

    def active_release(self, market):
        with self.db.get_session() as session:
            row = session.scalar(select(QuantModelRelease).where(
                QuantModelRelease.market == market, QuantModelRelease.active.is_(True)))
            if row is not None:
                session.expunge(row)
            return row

    def releases(self, market):
        with self.db.get_session() as session:
            return self._detach(session, list(session.scalars(select(QuantModelRelease).where(
                QuantModelRelease.market == market).order_by(QuantModelRelease.id.desc()))))

    def publish_release(self, market, cross_section_id, time_series_id, user_id, reason):
        from sqlalchemy import text
        from finance_analysis.quant.targets import stored_target_matches_production
        with self.db.session_scope() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"quant-release:{market}"})
            runs = [session.get(ModelRun, key, with_for_update=True) for key in (cross_section_id, time_series_id)]
            for run, key in zip(runs, ("cross_section_lgbm", "time_series_lgbm")):
                if (run is None or run.market != market or run.model_key != key or
                        run.status not in {"candidate", "production", "retired"} or not run.artifact_uri):
                    raise ValueError("A compatible completed pair is required")
                self._require_supported_universe_row(session, market, run.universe_id)
                if run.feature_config != {"base": "Alpha158"} or not stored_target_matches_production(key, run.target_config):
                    raise ValueError("Model feature or target contract is incompatible")
            if runs[0].universe_id != runs[1].universe_id:
                raise ValueError("Models must use the same universe")
            session.execute(update(QuantModelRelease).where(QuantModelRelease.market == market).values(active=False))
            session.execute(update(ModelRun).where(ModelRun.market == market, ModelRun.status == "production")
                            .values(status="retired"))
            session.flush()
            for run in runs:
                run.status = "production"
                session.add(ModelPublication(model_run_id=run.id, published_by=user_id, reason=reason))
            release = QuantModelRelease(market=market, cross_section_id=cross_section_id,
                                        time_series_id=time_series_id, reason=reason)
            session.add(release)
            session.flush()
            session.expunge(release)
            return release

    def create_experiment(self, market, universe_id, uid, version, date_from, date_to):
        from finance_analysis.quant.targets import production_target_config
        with self.db.session_scope() as session:
            runs = []
            for key in ("cross_section_lgbm", "time_series_lgbm"):
                definition = session.scalar(select(ModelDefinition).where(ModelDefinition.key == key))
                if definition is None or not definition.enabled:
                    raise ValueError("Model definition is unavailable")
                row = ModelRun(uid=uid, market=market, universe_id=universe_id,
                               model_definition_id=definition.id, model_key=key, model_version=version,
                               run_type="walk_forward", status="draft", progress=0,
                               train_start=date_from, train_end=date_to,
                               feature_config={"base": "Alpha158"}, target_config=production_target_config(key),
                               split_config={"train_years": 3, "valid_months": 3, "test_months": 3,
                                             "retrain_frequency_months": 3, "embargo_days": 2, "prediction_horizon": 5})
                session.add(row)
                runs.append(row)
            session.flush()
            return [row.id for row in runs]
