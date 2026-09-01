"""Transactional repository boundary for quant research data."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.quant import (
    DailyFeatureSnapshot, MarketRegimeSnapshot, ModelDefinition, ModelPublication,
    ModelRun, ModelSignal, PortfolioRecommendation, PortfolioRecommendationItem,
    QuantDatasetSnapshot, QuantUniverse, SectorRegimeSnapshot,
)
from finance_analysis.database.models.stock import MarketDataSymbol, StockDaily
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
        canonical_codes = sorted(
            {str(code or "").strip().upper() for code in codes if str(code or "").strip()}
        )
        if not canonical_codes:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(MarketDataSymbol.code, MarketDataSymbol.name).where(
                    MarketDataSymbol.code.in_(canonical_codes)
                )
            ).all()
        return {str(code): str(name).strip() for code, name in rows if str(name or "").strip()}

    def list_universes(self, market: str | None = None, enabled: bool | None = True) -> list[QuantUniverse]:
        clauses = [QuantUniverse.key.in_(tuple(DEFAULT_QUANT_UNIVERSES.values()))]
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
                        MarketDataSymbol.code.label("instrument"),
                        StockDaily.date.label("datetime"),
                        StockDaily.open,
                        StockDaily.high,
                        StockDaily.low,
                        StockDaily.close,
                        StockDaily.volume,
                        StockDaily.amount,
                        StockDaily.data_source.label("daily_data_source"),
                    )
                    .join(StockDaily, StockDaily.symbol_id == MarketDataSymbol.id)
                    .where(
                        MarketDataSymbol.market == market.upper(),
                        MarketDataSymbol.code.in_(codes),
                        StockDaily.date.between(start, end),
                    )
                    .order_by(MarketDataSymbol.code, StockDaily.date)
                ).mappings()
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
                raise ValueError(
                    f"Dataset is referenced by model run {referenced_run_id}; delete its model runs first"
                )
            result = {"id": row.id, "artifact_uri": row.artifact_uri}
            session.delete(row)
            session.flush()
            return result

    def upsert_daily_features(self, model, constraint: str, values: list[dict[str, Any]], key_fields: set[str]) -> None:
        with self.db.session_scope() as session:
            for value in values:
                session.execute(pg_insert(model).values(**value).on_conflict_do_update(
                    constraint=constraint, set_={key: val for key, val in value.items() if key not in key_fields}
                ))

    def save_daily_features(self, values: list[dict[str, Any]]) -> None:
        self.upsert_daily_features(DailyFeatureSnapshot, "uix_daily_feature_snapshot", values, {"trade_date", "symbol_id", "feature_version"})

    def feature_context(self, trade_date: date, feature_version: str) -> dict[int, dict[str, Any]]:
        with self.db.get_session() as session:
            rows = session.scalars(
                select(DailyFeatureSnapshot).where(
                    DailyFeatureSnapshot.trade_date == trade_date,
                    DailyFeatureSnapshot.feature_version == feature_version,
                )
            ).all()
            result = {}
            for daily in rows:
                features = daily.features or {}
                result[daily.symbol_id] = {
                    "sector_score": daily.sector_score,
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

    def market_regimes(
        self,
        market: str,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 365,
        model_version: str | None = None,
    ) -> list[MarketRegimeSnapshot]:
        clauses = [MarketRegimeSnapshot.market == market]
        if date_from: clauses.append(MarketRegimeSnapshot.trade_date >= date_from)
        if date_to: clauses.append(MarketRegimeSnapshot.trade_date <= date_to)
        if model_version: clauses.append(MarketRegimeSnapshot.model_version == model_version)
        with self.db.get_session() as session:
            ranked = select(
                MarketRegimeSnapshot.id.label("snapshot_id"),
                func.row_number().over(
                    partition_by=MarketRegimeSnapshot.trade_date,
                    order_by=(
                        desc(MarketRegimeSnapshot.generated_at),
                        desc(MarketRegimeSnapshot.id),
                    ),
                ).label("version_rank"),
            ).where(*clauses).subquery()
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

    def save_sector_regimes(self, values: Iterable[dict[str, Any]]) -> None:
        with self.db.session_scope() as session:
            for value in values:
                session.execute(pg_insert(SectorRegimeSnapshot).values(**value).on_conflict_do_update(
                    constraint="uix_sector_regime_version", set_={k: v for k, v in value.items() if k not in {"market", "trade_date", "sector_key", "model_version"}}
                ))

    def sector_regimes(
        self,
        market: str,
        trade_date: date | None = None,
        sector_key: str | None = None,
        model_version: str | None = None,
    ) -> list[SectorRegimeSnapshot]:
        clauses = [SectorRegimeSnapshot.market == market]
        if sector_key: clauses.append(SectorRegimeSnapshot.sector_key == sector_key)
        if model_version: clauses.append(SectorRegimeSnapshot.model_version == model_version)
        with self.db.get_session() as session:
            selection_clauses = list(clauses)
            if trade_date:
                selection_clauses.append(SectorRegimeSnapshot.trade_date == trade_date)
            selected = session.execute(
                select(
                    SectorRegimeSnapshot.trade_date,
                    SectorRegimeSnapshot.model_version,
                )
                .where(*selection_clauses)
                .order_by(
                    desc(SectorRegimeSnapshot.trade_date),
                    desc(SectorRegimeSnapshot.generated_at),
                    desc(SectorRegimeSnapshot.id),
                )
                .limit(1)
            ).first()
            if selected is None:
                return []
            rows = list(
                session.execute(
                    select(SectorRegimeSnapshot)
                    .where(
                        *clauses,
                        SectorRegimeSnapshot.trade_date == selected.trade_date,
                        SectorRegimeSnapshot.model_version == selected.model_version,
                    )
                    .order_by(SectorRegimeSnapshot.rank)
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
            result = {"id": row.id, "artifact_uri": row.artifact_uri}
            session.execute(delete(ModelPublication).where(ModelPublication.model_run_id == run_id))
            session.delete(row)
            session.flush()
            return result

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

    def replace_signals_and_save_portfolio(
        self,
        market: str,
        universe_id: int,
        trade_date: date,
        model_version: str,
        signals: list[dict[str, Any]],
        portfolio_values: dict[str, Any],
        portfolio_items: list[dict[str, Any]],
    ) -> PortfolioRecommendation:
        """Atomically publish one daily signal set and its portfolio recommendation."""
        with self.db.session_scope() as session:
            self._require_supported_universe_row(session, market, universe_id)
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
            session.add_all(
                PortfolioRecommendationItem(recommendation_id=row.id, **item)
                for item in portfolio_items
            )
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def latest_signals(
        self,
        market: str,
        universe_id: int | None = None,
        code: str | None = None,
        limit: int = 200,
        model_version: str | None = None,
    ) -> list[ModelSignal]:
        scope = [ModelSignal.market == market]
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
    ) -> list[ModelSignal]:
        clauses = [ModelSignal.market == market.upper(), ModelSignal.code == code.upper()]
        if universe_id is not None:
            clauses.append(ModelSignal.universe_id == universe_id)
        if model_version:
            clauses.append(ModelSignal.model_version == model_version)
        with self.db.get_session() as session:
            ranked = select(
                ModelSignal.id.label("signal_id"),
                func.row_number().over(
                    partition_by=ModelSignal.trade_date,
                    order_by=(desc(ModelSignal.generated_at), desc(ModelSignal.id)),
                ).label("version_rank"),
            ).where(*clauses).subquery()
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

    def latest_portfolios(
        self,
        market: str,
        universe_id: int | None = None,
        limit: int = 50,
        model_version: str | None = None,
    ) -> list[PortfolioRecommendation]:
        clauses = [PortfolioRecommendation.market == market]
        if universe_id: clauses.append(PortfolioRecommendation.universe_id == universe_id)
        if model_version: clauses.append(PortfolioRecommendation.model_version == model_version)
        with self.db.get_session() as session:
            ranked = select(
                PortfolioRecommendation.id.label("recommendation_id"),
                func.row_number().over(
                    partition_by=PortfolioRecommendation.trade_date,
                    order_by=(
                        desc(PortfolioRecommendation.generated_at),
                        desc(PortfolioRecommendation.id),
                    ),
                ).label("version_rank"),
            ).where(*clauses).subquery()
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
            items = list(session.execute(select(PortfolioRecommendationItem).where(PortfolioRecommendationItem.recommendation_id == row.id).order_by(PortfolioRecommendationItem.rank)).scalars())
            session.expunge(row); self._detach(session, items); return row, items

__all__ = ["QuantRepository"]
