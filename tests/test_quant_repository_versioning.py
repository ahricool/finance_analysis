from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from finance_analysis.database.models.quant import (
    MarketRegimeSnapshot,
    ModelSignal,
    PortfolioRecommendation,
    SectorRegimeSnapshot,
)
from finance_analysis.database.repositories.quant import QuantRepository


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class _SqliteManager:
    def __init__(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session


def _signal(identifier: int, code: str, model_version: str, generated_at: datetime) -> ModelSignal:
    return ModelSignal(
        id=identifier,
        trade_date=date(2026, 7, 22),
        instrument_id=identifier,
        code=code,
        market="US",
        universe_id=1,
        model_version=model_version,
        risk_penalty=0,
        raw_final_score=float(identifier),
        gated_final_score=float(identifier),
        final_score=float(identifier),
        universe_rank=identifier,
        signal="hold",
        target_position=0,
        vetoed=False,
        reasons=[],
        score_components={},
        generated_at=generated_at,
    )


def test_latest_quant_reads_do_not_mix_model_versions_on_the_same_trade_date() -> None:
    database = _SqliteManager()
    for table in (
        ModelSignal.__table__,
        MarketRegimeSnapshot.__table__,
        SectorRegimeSnapshot.__table__,
        PortfolioRecommendation.__table__,
    ):
        table.create(database.engine)

    older = datetime(2026, 7, 22, 8, tzinfo=timezone.utc)
    newer = datetime(2026, 7, 22, 9, tzinfo=timezone.utc)
    with Session(database.engine) as session:
        session.add_all(
            [
                _signal(1, "AAPL.US", "model-v1", older),
                _signal(2, "MSFT.US", "model-v1", older),
                _signal(3, "AAPL.US", "model-v2", newer),
                _signal(4, "MSFT.US", "model-v2", newer),
                MarketRegimeSnapshot(
                    id=1,
                    market="US",
                    trade_date=date(2026, 7, 22),
                    model_version="regime-v1",
                    regime="neutral",
                    market_score=0.5,
                    max_equity_exposure=0.4,
                    generated_at=older,
                ),
                MarketRegimeSnapshot(
                    id=2,
                    market="US",
                    trade_date=date(2026, 7, 22),
                    model_version="regime-v2",
                    regime="risk_on",
                    market_score=0.8,
                    max_equity_exposure=0.8,
                    generated_at=newer,
                ),
                *[
                    SectorRegimeSnapshot(
                        id=identifier,
                        market="US",
                        trade_date=date(2026, 7, 22),
                        sector_key=sector,
                        benchmark_code="SPY.US",
                        model_version=version,
                        sector_score=float(identifier),
                        rank=rank,
                        state="neutral",
                        generated_at=generated,
                    )
                    for identifier, sector, version, rank, generated in (
                        (1, "technology", "sector-v1", 1, older),
                        (2, "financials", "sector-v1", 2, older),
                        (3, "technology", "sector-v2", 1, newer),
                        (4, "financials", "sector-v2", 2, newer),
                    )
                ],
                PortfolioRecommendation(
                    id=1,
                    trade_date=date(2026, 7, 22),
                    market="US",
                    universe_id=1,
                    model_version="model-v1",
                    market_regime_id=1,
                    max_equity_exposure=0.4,
                    target_equity_exposure=0.3,
                    generated_at=older,
                ),
                PortfolioRecommendation(
                    id=2,
                    trade_date=date(2026, 7, 22),
                    market="US",
                    universe_id=1,
                    model_version="model-v2",
                    market_regime_id=2,
                    max_equity_exposure=0.8,
                    target_equity_exposure=0.7,
                    generated_at=newer,
                ),
            ]
        )
        session.commit()

    repository = QuantRepository(database)

    signals = repository.latest_signals("US", universe_id=1)
    history = repository.signal_history("US", "AAPL.US", universe_id=1)
    regimes = repository.market_regimes("US")
    sectors = repository.sector_regimes("US")
    portfolios = repository.latest_portfolios("US", universe_id=1)

    assert {row.model_version for row in signals} == {"model-v2"}
    assert [row.model_version for row in history] == ["model-v2"]
    assert [row.model_version for row in regimes] == ["regime-v2"]
    assert {row.model_version for row in sectors} == {"sector-v2"}
    assert [row.model_version for row in portfolios] == ["model-v2"]
    assert {row.model_version for row in repository.latest_signals("US", 1, model_version="model-v1")} == {"model-v1"}
