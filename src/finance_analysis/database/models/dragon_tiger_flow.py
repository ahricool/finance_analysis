"""One atomic normalized source generation per trading day."""

from sqlalchemy import Column, Date, DateTime, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base


class DragonTigerFlowBatch(Base):
    __tablename__ = "dragon_tiger_flow_batch"
    trade_date = Column(Date, primary_key=True)
    batch_id = Column(String(36), nullable=False, unique=True)
    rule_version = Column(String(64), nullable=False)
    collected_at = Column(DateTime(timezone=True), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
