"""Daily industry observations, independent of tradeable universes and strategies."""

from sqlalchemy import Column, Date, DateTime, Float, Integer, JSON, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class IndustryStrengthSnapshot(Base):
    __tablename__ = "industry_strength_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    industry_code = Column(String(32), nullable=False, index=True)
    industry_name = Column(String(128), nullable=False)
    close = Column(Float)
    ret_1d = Column(Float)
    ret_5d = Column(Float)
    ret_10d = Column(Float)
    ret_20d = Column(Float)
    rs_5d = Column(Float)
    rs_10d = Column(Float)
    rs_20d = Column(Float)
    rs_5d_percentile = Column(Float)
    rs_10d_percentile = Column(Float)
    rs_20d_percentile = Column(Float)
    strength_score = Column(Float)
    previous_5d_return = Column(Float)
    momentum_acceleration_5d = Column(Float)
    acceleration_percentile = Column(Float)
    turnover_ratio_5d = Column(Float)
    up_ratio = Column(Float)
    above_ma5_ratio = Column(Float)
    above_ma20_ratio = Column(Float)
    equal_weight_return = Column(Float)
    rs_5d_rank = Column(Integer)
    rs_10d_rank = Column(Integer)
    rs_20d_rank = Column(Integer)
    strength_rank = Column(Integer)
    rank_change_1d = Column(Integer)
    rank_change_3d = Column(Integer)
    rank_change_5d = Column(Integer)
    constituent_count = Column(Integer)
    valid_constituent_count = Column(Integer)
    up_count = Column(Integer)
    down_count = Column(Integer)
    flat_count = Column(Integer)
    state = Column(String(16), nullable=False)
    data_timestamp = Column(DateTime(timezone=True), nullable=False)
    members_observed_at = Column(DateTime(timezone=True), nullable=False)
    quality = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("trade_date", "industry_code", name="uix_industry_strength_date_code"),
        CheckConstraint("state IN ('EMERGING','STRONG','NEUTRAL','COOLING','WEAK')", name="ck_industry_strength_state"),
    )
