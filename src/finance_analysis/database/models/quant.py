"""Persistence models for versioned quantitative research results.

PostgreSQL remains the source of truth.  Qlib datasets and model binaries are
referenced by URI and never stored in JSON columns.
"""

from __future__ import annotations

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship


def json_object():
    return {}


def json_array():
    return []


class QuantUniverse(Base):
    __tablename__ = "quant_universe"
    id = Column(Integer, primary_key=True)
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    market = Column(String(8), nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    is_dynamic = Column(Boolean, nullable=False, default=False)
    benchmark_code = Column(String(32))
    sector_benchmark_mode = Column(String(32), nullable=False, default="member")
    config = Column(JSONB, nullable=False, default=json_object)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    members = relationship("QuantUniverseMember", cascade="all, delete-orphan", back_populates="universe")
    __table_args__ = (CheckConstraint("market IN ('US','HK','CN')", name="ck_quant_universe_market"),)


class QuantUniverseMember(Base):
    __tablename__ = "quant_universe_member"
    id = Column(BigInteger, primary_key=True)
    universe_id = Column(Integer, ForeignKey("quant_universe.id", ondelete="CASCADE"), nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    sector_key = Column(String(64))
    sector_benchmark_code = Column(String(32))
    weight = Column(Float)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    universe = relationship("QuantUniverse", back_populates="members")
    symbol = relationship("MarketDataSymbol")
    __table_args__ = (
        UniqueConstraint("universe_id", "symbol_id", "effective_from", name="uix_quant_member_period"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_quant_member_dates"),
        Index("ix_quant_member_active", "universe_id", "enabled", "effective_from", "effective_to"),
    )


class QuantDatasetSnapshot(Base):
    __tablename__ = "quant_dataset_snapshot"
    id = Column(BigInteger, primary_key=True)
    dataset_key = Column(String(128), nullable=False, unique=True)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("quant_universe.id", ondelete="RESTRICT"), nullable=False)
    frequency = Column(String(16), nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    price_mode = Column(String(24), nullable=False, default="forward_adjusted")
    feature_version = Column(String(64), nullable=False)
    source_revision = Column(String(64), nullable=False)
    code_commit = Column(String(64))
    artifact_uri = Column(Text)
    row_count = Column(BigInteger, nullable=False, default=0)
    symbol_count = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="pending")
    validation_result = Column(JSONB, nullable=False, default=json_object)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending','building','ready','failed')", name="ck_quant_dataset_status"),
        CheckConstraint(
            "price_mode IN ('raw','forward_adjusted')",
            name="ck_quant_dataset_price_mode",
        ),
        CheckConstraint("date_to >= date_from", name="ck_quant_dataset_dates"),
        Index("ix_quant_dataset_lookup", "market", "universe_id", "created_at"),
    )


class MarketRegimeSnapshot(Base):
    __tablename__ = "market_regime_snapshot"
    id = Column(BigInteger, primary_key=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    model_version = Column(String(64), nullable=False)
    regime = Column(String(16), nullable=False)
    market_score = Column(Float, nullable=False)
    max_equity_exposure = Column(Float, nullable=False)
    sector_permissions = Column(JSONB, nullable=False, default=json_object)
    features = Column(JSONB, nullable=False, default=json_object)
    reasons = Column(JSONB, nullable=False, default=json_array)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("market", "trade_date", "model_version", name="uix_market_regime_version"),
        CheckConstraint("regime IN ('risk_on','neutral','risk_off')", name="ck_market_regime_state"),
        Index("ix_market_regime_latest", "market", "trade_date"),
    )


class SectorRegimeSnapshot(Base):
    __tablename__ = "sector_regime_snapshot"
    id = Column(BigInteger, primary_key=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    sector_key = Column(String(64), nullable=False)
    benchmark_code = Column(String(32), nullable=False)
    model_version = Column(String(64), nullable=False)
    sector_score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    features = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("market", "trade_date", "sector_key", "model_version", name="uix_sector_regime_version"),
        CheckConstraint("state IN ('strong','neutral','weak','blocked')", name="ck_sector_regime_state"),
        Index("ix_sector_regime_latest", "market", "trade_date", "rank"),
    )


class MarketEvent(Base):
    __tablename__ = "market_event"
    id = Column(BigInteger, primary_key=True)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"))
    code = Column(String(32))
    market = Column(String(8), nullable=False)
    event_type = Column(String(40), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    effective_at = Column(DateTime(timezone=True))
    available_at = Column(DateTime(timezone=True), nullable=False)
    direction = Column(String(16), nullable=False)
    importance = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    surprise_value = Column(Float)
    source = Column(String(64), nullable=False)
    source_event_id = Column(String(160), nullable=False)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    raw_content = Column(Text)
    raw_payload = Column(JSONB, nullable=False, default=json_object)
    dedupe_key = Column(String(64), nullable=False, unique=True)
    review_status = Column(String(16), nullable=False, default="reviewed")
    extractor_model = Column(String(128))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    symbol = relationship("MarketDataSymbol")
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uix_market_event_source_id"),
        CheckConstraint("direction IN ('positive','negative','neutral')", name="ck_market_event_direction"),
        CheckConstraint("importance BETWEEN 0 AND 1", name="ck_market_event_importance"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_market_event_confidence"),
        Index("ix_market_event_available", "market", "available_at"),
        Index("ix_market_event_symbol_published", "symbol_id", "published_at"),
    )


class EventFeatureDaily(Base):
    __tablename__ = "event_feature_daily"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    feature_version = Column(String(64), nullable=False)
    earnings_surprise = Column(Float)
    revenue_surprise = Column(Float)
    guidance_change = Column(Float)
    rating_change = Column(Float)
    target_price_change = Column(Float)
    buyback_score = Column(Float)
    offering_score = Column(Float)
    regulatory_score = Column(Float)
    litigation_score = Column(Float)
    positive_event_count_3d = Column(Integer, nullable=False, default=0)
    negative_event_count_3d = Column(Integer, nullable=False, default=0)
    event_score = Column(Float, nullable=False, default=0)
    negative_event_veto = Column(Boolean, nullable=False, default=False)
    feature_payload = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("trade_date", "symbol_id", "feature_version", name="uix_event_feature_daily"),)


class DailyFeatureSnapshot(Base):
    __tablename__ = "daily_feature_snapshot"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    feature_version = Column(String(64), nullable=False)
    ret_1d = Column(Float); ret_5d = Column(Float); ret_20d = Column(Float); ret_60d = Column(Float)
    price_ma20_ratio = Column(Float); price_ma60_ratio = Column(Float); volume_ratio_5d = Column(Float)
    atr_14 = Column(Float); realized_vol_20d = Column(Float); distance_from_20d_high = Column(Float)
    gap_return = Column(Float); rsi_14 = Column(Float)
    relative_5d_to_market = Column(Float); relative_20d_to_market = Column(Float)
    relative_5d_to_sector = Column(Float); relative_20d_to_sector = Column(Float)
    market_score = Column(Float); sector_score = Column(Float); event_score = Column(Float)
    features = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("trade_date", "symbol_id", "feature_version", name="uix_daily_feature_snapshot"),
        Index("ix_daily_feature_date", "trade_date", "feature_version"),
    )


class ModelDefinition(Base):
    __tablename__ = "model_definition"
    id = Column(Integer, primary_key=True)
    key = Column(String(80), nullable=False, unique=True)
    name = Column(String(160), nullable=False)
    model_type = Column(String(24), nullable=False)
    task_type = Column(String(24), nullable=False)
    frequency = Column(String(16), nullable=False)
    target_definition = Column(JSONB, nullable=False, default=json_object)
    enabled = Column(Boolean, nullable=False, default=True)
    default_config = Column(JSONB, nullable=False, default=json_object)
    supported_markets = Column(JSONB, nullable=False, default=json_array)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (CheckConstraint("model_type IN ('market_regime','time_series','cross_section','fusion')", name="ck_model_definition_type"),)


class ModelRun(Base):
    __tablename__ = "model_run"
    id = Column(BigInteger, primary_key=True)
    uid = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    task_id = Column(String(64))
    model_definition_id = Column(Integer, ForeignKey("model_definition.id", ondelete="RESTRICT"), nullable=False)
    model_key = Column(String(80), nullable=False)
    model_version = Column(String(96), nullable=False)
    run_type = Column(String(24), nullable=False)
    market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("quant_universe.id", ondelete="RESTRICT"), nullable=False)
    dataset_snapshot_id = Column(BigInteger, ForeignKey("quant_dataset_snapshot.id", ondelete="RESTRICT"))
    train_start = Column(Date); train_end = Column(Date); valid_start = Column(Date); valid_end = Column(Date)
    test_start = Column(Date); test_end = Column(Date); prediction_date = Column(Date)
    status = Column(String(20), nullable=False, default="draft")
    progress = Column(Integer, nullable=False, default=0)
    parameters = Column(JSONB, nullable=False, default=json_object)
    split_config = Column(JSONB, nullable=False, default=json_object)
    feature_config = Column(JSONB, nullable=False, default=json_object)
    target_config = Column(JSONB, nullable=False, default=json_object)
    metrics = Column(JSONB, nullable=False, default=json_object)
    feature_importance = Column(JSONB, nullable=False, default=json_object)
    artifact_uri = Column(Text)
    artifact_digest = Column(String(64)); artifact_size = Column(BigInteger)
    code_commit = Column(String(64)); warnings = Column(JSONB, nullable=False, default=json_array); error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True)); finished_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("run_type IN ('train','backtest','predict','walk_forward')", name="ck_model_run_type"),
        CheckConstraint("status IN ('draft','training','candidate','production','retired','failed')", name="ck_model_run_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_model_run_progress"),
        Index("ix_model_run_lookup", "market", "model_key", "status", "created_at"),
        Index(
            "uix_model_run_production_market_key",
            "market",
            "model_key",
            unique=True,
            postgresql_where=text("status = 'production'"),
        ),
    )


class ModelPublication(Base):
    __tablename__ = "model_publication"
    id = Column(BigInteger, primary_key=True)
    model_run_id = Column(BigInteger, ForeignKey("model_run.id", ondelete="RESTRICT"), nullable=False)
    previous_model_run_id = Column(BigInteger, ForeignKey("model_run.id", ondelete="SET NULL"))
    published_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ModelPrediction(Base):
    __tablename__ = "model_prediction"
    id = Column(BigInteger, primary_key=True)
    model_run_id = Column(BigInteger, ForeignKey("model_run.id", ondelete="CASCADE"), nullable=False)
    trade_date = Column(Date, nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    raw_prediction = Column(Float, nullable=False); normalized_score = Column(Float, nullable=False)
    predicted_return = Column(Float); universe_rank = Column(Integer); sector_rank = Column(Integer)
    actual_return = Column(Float); actual_excess_return = Column(Float); evaluation_status = Column(String(20))
    features_digest = Column(String(64)); explanation = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (UniqueConstraint("model_run_id", "trade_date", "symbol_id", name="uix_model_prediction"),)


class ModelSignal(Base):
    __tablename__ = "model_signal"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False); market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("quant_universe.id", ondelete="RESTRICT"), nullable=False)
    model_version = Column(String(96), nullable=False)
    market_score = Column(Float); sector_score = Column(Float); event_score = Column(Float)
    time_series_score = Column(Float); cross_section_score = Column(Float); risk_penalty = Column(Float, nullable=False, default=0)
    raw_final_score = Column(Float, nullable=False); gated_final_score = Column(Float, nullable=False)
    final_score = Column(Float, nullable=False); universe_rank = Column(Integer); sector_rank = Column(Integer)
    predicted_return = Column(Float); signal = Column(String(16), nullable=False); target_position = Column(Float, nullable=False, default=0)
    vetoed = Column(Boolean, nullable=False, default=False); veto_reason = Column(Text)
    reasons = Column(JSONB, nullable=False, default=json_array); score_components = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint(
            "market", "universe_id", "trade_date", "symbol_id", "model_version",
            name="uix_model_signal_market_universe",
        ),
        Index("ix_model_signal_ranking", "market", "universe_id", "trade_date", "universe_rank"),
    )


class PortfolioRecommendation(Base):
    __tablename__ = "portfolio_recommendation"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False); market = Column(String(8), nullable=False)
    universe_id = Column(Integer, ForeignKey("quant_universe.id", ondelete="RESTRICT"), nullable=False)
    model_version = Column(String(96), nullable=False)
    market_regime_id = Column(BigInteger, ForeignKey("market_regime_snapshot.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), nullable=False, default="ready")
    max_equity_exposure = Column(Float, nullable=False); target_equity_exposure = Column(Float, nullable=False)
    config = Column(JSONB, nullable=False, default=json_object); summary = Column(JSONB, nullable=False, default=json_object)
    warnings = Column(JSONB, nullable=False, default=json_array); generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    items = relationship("PortfolioRecommendationItem", cascade="all, delete-orphan", back_populates="recommendation")
    __table_args__ = (UniqueConstraint("trade_date", "universe_id", "model_version", name="uix_portfolio_recommendation"),)


class PortfolioRecommendationItem(Base):
    __tablename__ = "portfolio_recommendation_item"
    id = Column(BigInteger, primary_key=True)
    recommendation_id = Column(BigInteger, ForeignKey("portfolio_recommendation.id", ondelete="CASCADE"), nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False); sector_key = Column(String(64)); rank = Column(Integer, nullable=False); previous_rank = Column(Integer)
    action = Column(String(16), nullable=False); current_weight = Column(Float, nullable=False, default=0)
    target_weight = Column(Float, nullable=False, default=0); weight_change = Column(Float, nullable=False, default=0)
    final_score = Column(Float, nullable=False); predicted_return = Column(Float); signal = Column(String(16), nullable=False)
    reasons = Column(JSONB, nullable=False, default=json_array); constraints = Column(JSONB, nullable=False, default=json_object)
    recommendation = relationship("PortfolioRecommendation", back_populates="items")
    __table_args__ = (
        UniqueConstraint("recommendation_id", "symbol_id", name="uix_portfolio_item"),
        CheckConstraint("action IN ('buy','increase','hold','reduce','sell','watch','blocked')", name="ck_portfolio_item_action"),
    )


class IntradayConfirmation(Base):
    __tablename__ = "intraday_confirmation"
    id = Column(BigInteger, primary_key=True)
    trade_date = Column(Date, nullable=False); symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="RESTRICT"), nullable=False)
    code = Column(String(32), nullable=False)
    recommendation_item_id = Column(BigInteger, ForeignKey("portfolio_recommendation_item.id", ondelete="CASCADE"), nullable=False)
    evaluated_at = Column(DateTime(timezone=True), nullable=False); decision = Column(String(24), nullable=False); confidence = Column(Float, nullable=False)
    price = Column(Float); vwap = Column(Float); price_vs_vwap = Column(Float); vwap_slope = Column(Float)
    first_30m_return = Column(Float); intraday_high_drawdown = Column(Float); volume_ratio = Column(Float)
    relative_strength_market = Column(Float); relative_strength_sector = Column(Float)
    reasons = Column(JSONB, nullable=False, default=json_array); features = Column(JSONB, nullable=False, default=json_object)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("decision IN ('confirm','wait','reject','expired','insufficient_data')", name="ck_intraday_decision"),
        Index("ix_intraday_latest", "trade_date", "symbol_id", "evaluated_at"),
    )


QUANT_TABLES = (
    QuantUniverse, QuantUniverseMember, QuantDatasetSnapshot, MarketRegimeSnapshot, SectorRegimeSnapshot,
    MarketEvent, EventFeatureDaily, DailyFeatureSnapshot, ModelDefinition, ModelRun, ModelPublication,
    ModelPrediction, ModelSignal, PortfolioRecommendation, PortfolioRecommendationItem, IntradayConfirmation,
)
