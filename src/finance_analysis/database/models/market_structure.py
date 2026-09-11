"""One official market structure snapshot per market session."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Float, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class MarketStructureSnapshot(Base):
    __tablename__ = "market_structure_snapshot"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False)
    trade_date = Column(Date, nullable=False)
    benchmark_return_5d = Column(Float)
    median_member_return_5d = Column(Float)
    breadth_divergence_5d = Column(Float)
    member_positive_ratio_5d = Column(Float)
    member_above_ma10_ratio = Column(Float)
    member_above_ma20_ratio = Column(Float)
    rotation_velocity_1d = Column(Float)
    rotation_velocity_3d = Column(Float)
    rotation_velocity_5d = Column(Float)
    leadership_concentration_1d = Column(Float)
    leadership_concentration_5d = Column(Float)
    leadership_hhi_5d = Column(Float)
    metrics_json = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        UniqueConstraint("market", "trade_date", name="uix_market_structure_market_date"),
        CheckConstraint("market IN ('CN', 'US')", name="ck_market_structure_market"),
    )
