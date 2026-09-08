from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from alembic.config import Config
from alembic.script import ScriptDirectory

from finance_analysis.database.models.quant import (  # pragma: allowlist secret
    MarketRegimeSnapshot,
    ModelSignal,
    PortfolioRecommendationItem,
    QUANT_TABLES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_quant_simplification_is_the_single_head_and_matches_current_orm() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == "0046_simplify_quant"

    table_names = {model.__tablename__ for model in QUANT_TABLES}
    assert table_names.isdisjoint(
        {
            "market_event",
            "event_feature_daily",
            "daily_feature_snapshot",
            "model_prediction",
            "sector_regime_snapshot",
        }
    )
    assert set(MarketRegimeSnapshot.__table__.columns.keys()) == {
        "id",
        "market",
        "trade_date",
        "model_version",
        "regime",
        "market_score",
        "max_equity_exposure",
        "features",
        "reasons",
        "generated_at",
    }
    assert set(ModelSignal.__table__.columns.keys()) == {
        "id",
        "trade_date",
        "instrument_id",
        "code",
        "market",
        "universe_id",
        "model_version",
        "market_score",
        "time_series_score",
        "cross_section_score",
        "risk_penalty",
        "final_score",
        "universe_rank",
        "predicted_return",
        "signal",
        "reasons",
        "score_components",
        "generated_at",
    }
    assert set(PortfolioRecommendationItem.__table__.columns.keys()) == {
        "id",
        "recommendation_id",
        "instrument_id",
        "code",
        "rank",
        "target_weight",
        "final_score",
        "predicted_return",
        "signal",
        "reasons",
        "constraints",
    }


def test_quant_simplification_revision_drops_legacy_schema() -> None:
    path = ROOT / "alembic" / "versions" / "0046_simplify_quant_pipeline.py"
    spec = importlib.util.spec_from_file_location("quant_simplification_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    migration.op = MagicMock()

    migration.upgrade()

    assert migration.revision == "0046_simplify_quant"
    assert migration.down_revision == "0045_calendar_sources"
    assert [call.args[0] for call in migration.op.execute.call_args_list] == [
        "DELETE FROM portfolio_recommendation",
        "DELETE FROM model_signal",
    ]
    assert {call.args[0] for call in migration.op.drop_table.call_args_list} == {
        "market_event",
        "event_feature_daily",
        "daily_feature_snapshot",
        "model_prediction",
        "sector_regime_snapshot",
    }
    dropped_columns = {
        (call.args[0], call.args[1])
        for call in migration.op.drop_column.call_args_list
    }
    assert ("market_regime_snapshot", "sector_permissions") in dropped_columns
    assert ("model_signal", "event_score") in dropped_columns
    assert ("model_signal", "gated_final_score") in dropped_columns
    assert ("portfolio_recommendation_item", "current_weight") in dropped_columns
    migration.op.drop_constraint.assert_called_once_with(
        "ck_portfolio_item_action",
        "portfolio_recommendation_item",
        type_="check",
    )
