# -*- coding: utf-8 -*-
"""LLM usage ORM models."""

from sqlalchemy import Column, DateTime, Integer, String

from finance_analysis.database.base import Base
from finance_analysis.core.time import utc_now


class LLMUsage(Base):
    """One row per unified LLM client call for token-usage audit logging."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(Integer, nullable=True, index=True)
    call_type = Column(String(32), nullable=False, index=True)
    model = Column(String(128), nullable=True)
    backend = Column(String(8), nullable=False, default="api")
    engine = Column(String(16), nullable=True)
    status = Column(String(16), nullable=False, default="success")
    duration_ms = Column(Integer, nullable=False, default=0)
    error = Column(String(500), nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    called_at = Column(DateTime(timezone=True), default=utc_now, index=True)
