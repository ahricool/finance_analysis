"""One immutable input and at most one final decision per market session."""

from sqlalchemy import Column, String, Date, DateTime, Text, JSON, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class SignalCenterRun(Base):
    __tablename__ = "signal_center_run"
    market = Column(String(8), primary_key=True)
    signal_date = Column(Date, primary_key=True)
    status = Column(String(16), nullable=False)
    selected_symbol = Column(String(32))
    decision = Column(String(16))
    confidence = Column(String(8))
    candidate_snapshot = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    analysis = Column(JSONB().with_variant(JSON(), "sqlite"))
    model = Column(String(160))
    backend = Column(String(16))
    prompt_version = Column(String(32), nullable=False)
    system_prompt = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    screening = Column(JSONB().with_variant(JSON(), "sqlite"))
    final_prompt = Column(Text)
    raw_response = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("market IN ('CN','US')", name="ck_signal_center_market"),
        CheckConstraint("status IN ('pending','completed','failed','skipped')", name="ck_signal_center_status"),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('low','medium','high')", name="ck_signal_center_confidence"
        ),
        CheckConstraint(
            "(status = 'completed' AND decision IS NOT NULL AND analysis IS NOT NULL AND confidence IS NOT NULL AND "
            "((decision = 'BUY' AND selected_symbol IS NOT NULL) OR "
            "(decision = 'NO_TRADE' AND selected_symbol IS NULL))) OR "
            "(status <> 'completed' AND decision IS NULL AND selected_symbol IS NULL)",
            name="ck_signal_center_decision",
        ),
    )
