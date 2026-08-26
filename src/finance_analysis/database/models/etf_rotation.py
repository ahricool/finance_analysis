"""PostgreSQL snapshots for the independent ETF rotation domain."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class ETFMomentumSnapshot(Base):
    __tablename__ = "etf_momentum_snapshot"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    symbol_id = Column(Integer, ForeignKey("market_data_symbol.id", ondelete="CASCADE"), nullable=False)
    ret_1d = Column(Float, nullable=False)
    ret_5d = Column(Float, nullable=False)
    ret_10d = Column(Float, nullable=False)
    ret_20d = Column(Float, nullable=False)
    ret_30d = Column(Float, nullable=False)
    ret_60d = Column(Float, nullable=False)
    rank_1d = Column(Integer, nullable=False)
    rank_5d = Column(Integer, nullable=False)
    rank_10d = Column(Integer, nullable=False)
    rank_20d = Column(Integer, nullable=False)
    rank_30d = Column(Integer, nullable=False)
    rank_60d = Column(Integer, nullable=False)
    pct_rank_1d = Column(Float, nullable=False)
    pct_rank_5d = Column(Float, nullable=False)
    pct_rank_10d = Column(Float, nullable=False)
    pct_rank_20d = Column(Float, nullable=False)
    pct_rank_30d = Column(Float, nullable=False)
    pct_rank_60d = Column(Float, nullable=False)
    previous_5d_return = Column(Float, nullable=False)
    momentum_acceleration = Column(Float, nullable=False)
    rank_change_1d = Column(Integer)
    rank_change_3d = Column(Integer)
    rank_change_5d = Column(Integer)
    ma20_ratio = Column(Float, nullable=False)
    ma60_ratio = Column(Float, nullable=False)
    volume_ratio_5d = Column(Float)
    avg_amount_20d = Column(Float)
    realized_vol_20d = Column(Float, nullable=False)
    reference_price = Column(Float)
    stop_loss_pct = Column(Float)
    suggested_stop_price = Column(Float)
    distance_from_20d_high = Column(Float, nullable=False)
    momentum_score = Column(Float, nullable=False)
    entry_score = Column(Float, nullable=False)
    state = Column(String(16), nullable=False)
    overheated = Column(Boolean, nullable=False, default=False)
    candidate_rank = Column(Integer)
    is_candidate = Column(Boolean, nullable=False, default=False)
    score_components = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    symbol = relationship("MarketDataSymbol", lazy="joined")

    __table_args__ = (
        UniqueConstraint("trade_date", "symbol_id", name="uix_etf_momentum_snapshot_date_symbol"),
        CheckConstraint("market IN ('CN', 'US')", name="ck_etf_momentum_snapshot_market"),
        CheckConstraint("momentum_score BETWEEN 0 AND 100", name="ck_etf_momentum_score_range"),
        CheckConstraint("entry_score BETWEEN 0 AND 100", name="ck_etf_entry_score_range"),
        CheckConstraint("reference_price IS NULL OR reference_price > 0", name="ck_etf_reference_price_positive"),
        CheckConstraint(
            "stop_loss_pct IS NULL OR (stop_loss_pct >= 0 AND stop_loss_pct < 1)",
            name="ck_etf_stop_loss_pct_range",
        ),
        CheckConstraint(
            "suggested_stop_price IS NULL OR "
            "(suggested_stop_price > 0 AND reference_price IS NOT NULL AND suggested_stop_price <= reference_price)",
            name="ck_etf_suggested_stop_price_positive",
        ),
        CheckConstraint(
            "(reference_price IS NULL AND stop_loss_pct IS NULL AND suggested_stop_price IS NULL) OR "
            "(reference_price IS NOT NULL AND stop_loss_pct IS NOT NULL AND suggested_stop_price IS NOT NULL)",
            name="ck_etf_stop_loss_metadata_complete",
        ),
        CheckConstraint(
            "rank_1d > 0 AND rank_5d > 0 AND rank_10d > 0 AND rank_20d > 0 AND rank_30d > 0 AND rank_60d > 0",
            name="ck_etf_momentum_ranks_positive",
        ),
        CheckConstraint(
            "pct_rank_1d BETWEEN 0 AND 100 AND pct_rank_5d BETWEEN 0 AND 100 "
            "AND pct_rank_10d BETWEEN 0 AND 100 AND pct_rank_20d BETWEEN 0 AND 100 "
            "AND pct_rank_30d BETWEEN 0 AND 100 AND pct_rank_60d BETWEEN 0 AND 100",
            name="ck_etf_momentum_pct_ranks_range",
        ),
        CheckConstraint(
            "state IN ('EMERGING','TRENDING','STRONG','COOLING','EXHAUSTED','WEAK','NEUTRAL')",
            name="ck_etf_momentum_state",
        ),
        CheckConstraint("candidate_rank IS NULL OR candidate_rank > 0", name="ck_etf_candidate_rank_positive"),
        Index("ix_etf_momentum_snapshot_market_date_entry", "market", "trade_date", "entry_score"),
        Index("ix_etf_momentum_snapshot_symbol_date", "symbol_id", "trade_date"),
        Index(
            "ix_etf_momentum_snapshot_market_date_candidate",
            "market",
            "trade_date",
            "is_candidate",
            "candidate_rank",
        ),
    )


__all__ = ["ETFMomentumSnapshot"]
