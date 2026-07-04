"""Add versioned quantitative research storage.

Revision ID: 0017_quant_research
Revises: 0016_dual_engine_backtests
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_quant_research"
down_revision: Union[str, Sequence[str], None] = "0016_dual_engine_backtests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "quant_universe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_dynamic", sa.Boolean(), nullable=False),
        sa.Column("benchmark_code", sa.String(32)),
        sa.Column("sector_benchmark_mode", sa.String(32), nullable=False),
        sa.Column("config", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('US','HK','CN')", name="ck_quant_universe_market"),
    )
    op.create_table(
        "quant_universe_member",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("sector_key", sa.String(64)),
        sa.Column("sector_benchmark_code", sa.String(32)),
        sa.Column("weight", sa.Float()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["universe_id"], ["quant_universe.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("universe_id", "symbol_id", "effective_from", name="uix_quant_member_period"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_quant_member_dates"),
    )
    op.create_index(
        "ix_quant_member_active",
        "quant_universe_member",
        ["universe_id", "enabled", "effective_from", "effective_to"],
    )
    op.create_table(
        "quant_dataset_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("dataset_key", sa.String(128), nullable=False, unique=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("price_mode", sa.String(16), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("code_commit", sa.String(64)),
        sa.Column("artifact_uri", sa.Text()),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("validation_result", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["universe_id"], ["quant_universe.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('pending','building','ready','failed')", name="ck_quant_dataset_status"),
        sa.CheckConstraint("price_mode IN ('raw','adjusted')", name="ck_quant_dataset_price_mode"),
        sa.CheckConstraint("date_to >= date_from", name="ck_quant_dataset_dates"),
    )
    op.create_index("ix_quant_dataset_lookup", "quant_dataset_snapshot", ["market", "universe_id", "created_at"])
    op.create_table(
        "market_regime_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("regime", sa.String(16), nullable=False),
        sa.Column("market_score", sa.Float(), nullable=False),
        sa.Column("max_equity_exposure", sa.Float(), nullable=False),
        sa.Column("sector_permissions", jsonb, nullable=False),
        sa.Column("features", jsonb, nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market", "trade_date", "model_version", name="uix_market_regime_version"),
        sa.CheckConstraint("regime IN ('risk_on','neutral','risk_off')", name="ck_market_regime_state"),
    )
    op.create_index("ix_market_regime_latest", "market_regime_snapshot", ["market", "trade_date"])
    op.create_table(
        "sector_regime_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sector_key", sa.String(64), nullable=False),
        sa.Column("benchmark_code", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("sector_score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("features", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market", "trade_date", "sector_key", "model_version", name="uix_sector_regime_version"),
        sa.CheckConstraint("state IN ('strong','neutral','weak','blocked')", name="ck_sector_regime_state"),
    )
    op.create_index("ix_sector_regime_latest", "sector_regime_snapshot", ["market", "trade_date", "rank"])
    op.create_table(
        "market_event",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol_id", sa.Integer()),
        sa.Column("code", sa.String(32)),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("surprise_value", sa.Float()),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(160), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("raw_content", sa.Text()),
        sa.Column("raw_payload", jsonb, nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("extractor_model", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source", "source_event_id", name="uix_market_event_source_id"),
        sa.CheckConstraint("direction IN ('positive','negative','neutral')", name="ck_market_event_direction"),
        sa.CheckConstraint("importance BETWEEN 0 AND 1", name="ck_market_event_importance"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_market_event_confidence"),
    )
    op.create_index("ix_market_event_available", "market_event", ["market", "available_at"])
    op.create_index("ix_market_event_symbol_published", "market_event", ["symbol_id", "published_at"])
    op.create_table(
        "event_feature_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("earnings_surprise", sa.Float()),
        sa.Column("revenue_surprise", sa.Float()),
        sa.Column("guidance_change", sa.Float()),
        sa.Column("rating_change", sa.Float()),
        sa.Column("target_price_change", sa.Float()),
        sa.Column("buyback_score", sa.Float()),
        sa.Column("offering_score", sa.Float()),
        sa.Column("regulatory_score", sa.Float()),
        sa.Column("litigation_score", sa.Float()),
        sa.Column("positive_event_count_3d", sa.Integer(), nullable=False),
        sa.Column("negative_event_count_3d", sa.Integer(), nullable=False),
        sa.Column("event_score", sa.Float(), nullable=False),
        sa.Column("negative_event_veto", sa.Boolean(), nullable=False),
        sa.Column("feature_payload", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trade_date", "symbol_id", "feature_version", name="uix_event_feature_daily"),
    )
    op.create_table(
        "daily_feature_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("ret_1d", sa.Float()),
        sa.Column("ret_5d", sa.Float()),
        sa.Column("ret_20d", sa.Float()),
        sa.Column("ret_60d", sa.Float()),
        sa.Column("price_ma20_ratio", sa.Float()),
        sa.Column("price_ma60_ratio", sa.Float()),
        sa.Column("volume_ratio_5d", sa.Float()),
        sa.Column("atr_14", sa.Float()),
        sa.Column("realized_vol_20d", sa.Float()),
        sa.Column("distance_from_20d_high", sa.Float()),
        sa.Column("gap_return", sa.Float()),
        sa.Column("rsi_14", sa.Float()),
        sa.Column("relative_5d_to_market", sa.Float()),
        sa.Column("relative_20d_to_market", sa.Float()),
        sa.Column("relative_5d_to_sector", sa.Float()),
        sa.Column("relative_20d_to_sector", sa.Float()),
        sa.Column("market_score", sa.Float()),
        sa.Column("sector_score", sa.Float()),
        sa.Column("event_score", sa.Float()),
        sa.Column("features", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trade_date", "symbol_id", "feature_version", name="uix_daily_feature_snapshot"),
    )
    op.create_index("ix_daily_feature_date", "daily_feature_snapshot", ["trade_date", "feature_version"])
    op.create_table(
        "model_definition",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("model_type", sa.String(24), nullable=False),
        sa.Column("task_type", sa.String(24), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("target_definition", jsonb, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_config", jsonb, nullable=False),
        sa.Column("supported_markets", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "model_type IN ('market_regime','time_series','cross_section','fusion')", name="ck_model_definition_type"
        ),
    )
    op.create_table(
        "model_run",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(64)),
        sa.Column("model_definition_id", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(80), nullable=False),
        sa.Column("model_version", sa.String(96), nullable=False),
        sa.Column("run_type", sa.String(24), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("dataset_snapshot_id", sa.BigInteger()),
        sa.Column("train_start", sa.Date()),
        sa.Column("train_end", sa.Date()),
        sa.Column("valid_start", sa.Date()),
        sa.Column("valid_end", sa.Date()),
        sa.Column("test_start", sa.Date()),
        sa.Column("test_end", sa.Date()),
        sa.Column("prediction_date", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("parameters", jsonb, nullable=False),
        sa.Column("split_config", jsonb, nullable=False),
        sa.Column("feature_config", jsonb, nullable=False),
        sa.Column("target_config", jsonb, nullable=False),
        sa.Column("metrics", jsonb, nullable=False),
        sa.Column("feature_importance", jsonb, nullable=False),
        sa.Column("artifact_uri", sa.Text()),
        sa.Column("artifact_digest", sa.String(64)),
        sa.Column("artifact_size", sa.BigInteger()),
        sa.Column("code_commit", sa.String(64)),
        sa.Column("warnings", jsonb, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["uid"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_definition_id"], ["model_definition.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["universe_id"], ["quant_universe.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dataset_snapshot_id"], ["quant_dataset_snapshot.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("run_type IN ('train','backtest','predict','walk_forward')", name="ck_model_run_type"),
        sa.CheckConstraint(
            "status IN ('draft','training','candidate','production','retired','failed')", name="ck_model_run_status"
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_model_run_progress"),
    )
    op.create_index("ix_model_run_lookup", "model_run", ["market", "model_key", "status", "created_at"])
    op.create_table(
        "model_publication",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("model_run_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_model_run_id", sa.BigInteger()),
        sa.Column("published_by", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_model_run_id"], ["model_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "model_prediction",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("model_run_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("raw_prediction", sa.Float(), nullable=False),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("predicted_return", sa.Float()),
        sa.Column("universe_rank", sa.Integer()),
        sa.Column("sector_rank", sa.Integer()),
        sa.Column("actual_return", sa.Float()),
        sa.Column("actual_excess_return", sa.Float()),
        sa.Column("evaluation_status", sa.String(20)),
        sa.Column("features_digest", sa.String(64)),
        sa.Column("explanation", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("model_run_id", "trade_date", "symbol_id", name="uix_model_prediction"),
    )
    op.create_table(
        "model_signal",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(96), nullable=False),
        sa.Column("market_score", sa.Float()),
        sa.Column("sector_score", sa.Float()),
        sa.Column("event_score", sa.Float()),
        sa.Column("time_series_score", sa.Float()),
        sa.Column("cross_section_score", sa.Float()),
        sa.Column("risk_penalty", sa.Float(), nullable=False),
        sa.Column("raw_final_score", sa.Float(), nullable=False),
        sa.Column("gated_final_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("universe_rank", sa.Integer()),
        sa.Column("sector_rank", sa.Integer()),
        sa.Column("predicted_return", sa.Float()),
        sa.Column("signal", sa.String(16), nullable=False),
        sa.Column("target_position", sa.Float(), nullable=False),
        sa.Column("vetoed", sa.Boolean(), nullable=False),
        sa.Column("veto_reason", sa.Text()),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("score_components", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["universe_id"], ["quant_universe.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("trade_date", "symbol_id", "model_version", name="uix_model_signal"),
    )
    op.create_index("ix_model_signal_ranking", "model_signal", ["market", "universe_id", "trade_date", "universe_rank"])
    op.create_table(
        "portfolio_recommendation",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(96), nullable=False),
        sa.Column("market_regime_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_equity_exposure", sa.Float(), nullable=False),
        sa.Column("target_equity_exposure", sa.Float(), nullable=False),
        sa.Column("config", jsonb, nullable=False),
        sa.Column("summary", jsonb, nullable=False),
        sa.Column("warnings", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["universe_id"], ["quant_universe.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_regime_id"], ["market_regime_snapshot.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("trade_date", "universe_id", "model_version", name="uix_portfolio_recommendation"),
    )
    op.create_table(
        "portfolio_recommendation_item",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("recommendation_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("sector_key", sa.String(64)),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("previous_rank", sa.Integer()),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("current_weight", sa.Float(), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("weight_change", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("predicted_return", sa.Float()),
        sa.Column("signal", sa.String(16), nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("constraints", jsonb, nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["portfolio_recommendation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("recommendation_id", "symbol_id", name="uix_portfolio_item"),
        sa.CheckConstraint(
            "action IN ('buy','increase','hold','reduce','sell','watch','blocked')", name="ck_portfolio_item_action"
        ),
    )
    op.create_table(
        "intraday_confirmation",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("recommendation_item_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("price", sa.Float()),
        sa.Column("vwap", sa.Float()),
        sa.Column("price_vs_vwap", sa.Float()),
        sa.Column("vwap_slope", sa.Float()),
        sa.Column("first_30m_return", sa.Float()),
        sa.Column("intraday_high_drawdown", sa.Float()),
        sa.Column("volume_ratio", sa.Float()),
        sa.Column("relative_strength_market", sa.Float()),
        sa.Column("relative_strength_sector", sa.Float()),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("features", jsonb, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["market_data_symbol.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recommendation_item_id"], ["portfolio_recommendation_item.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "decision IN ('confirm','wait','reject','expired','insufficient_data')", name="ck_intraday_decision"
        ),
    )
    op.create_index("ix_intraday_latest", "intraday_confirmation", ["trade_date", "symbol_id", "evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_intraday_latest", table_name="intraday_confirmation")
    op.drop_table("intraday_confirmation")
    op.drop_table("portfolio_recommendation_item")
    op.drop_table("portfolio_recommendation")
    op.drop_index("ix_model_signal_ranking", table_name="model_signal")
    op.drop_table("model_signal")
    op.drop_table("model_prediction")
    op.drop_table("model_publication")
    op.drop_index("ix_model_run_lookup", table_name="model_run")
    op.drop_table("model_run")
    op.drop_table("model_definition")
    op.drop_index("ix_daily_feature_date", table_name="daily_feature_snapshot")
    op.drop_table("daily_feature_snapshot")
    op.drop_table("event_feature_daily")
    op.drop_index("ix_market_event_symbol_published", table_name="market_event")
    op.drop_index("ix_market_event_available", table_name="market_event")
    op.drop_table("market_event")
    op.drop_index("ix_sector_regime_latest", table_name="sector_regime_snapshot")
    op.drop_table("sector_regime_snapshot")
    op.drop_index("ix_market_regime_latest", table_name="market_regime_snapshot")
    op.drop_table("market_regime_snapshot")
    op.drop_index("ix_quant_dataset_lookup", table_name="quant_dataset_snapshot")
    op.drop_table("quant_dataset_snapshot")
    op.drop_index("ix_quant_member_active", table_name="quant_universe_member")
    op.drop_table("quant_universe_member")
    op.drop_table("quant_universe")
