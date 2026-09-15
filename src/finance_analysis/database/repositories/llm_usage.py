"""LLM attempt statistics; detailed request audit lives in daily JSONL files."""

from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import and_, desc, func, select
from finance_analysis.database.base import ensure_aware_datetime
from finance_analysis.database.models import LLMUsage
from finance_analysis.core.time import utc_now


class LLMUsageMixin:
    def record_llm_usage(
        self,
        *,
        call_type: str,
        backend: str,
        engine: Optional[str],
        model: Optional[str],
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        error: Optional[str] = None,
        uid: Optional[int] = None,
    ) -> None:
        with self.session_scope() as session:
            session.add(
                LLMUsage(
                    uid=uid,
                    call_type=call_type,
                    backend=backend,
                    engine=engine,
                    model=model,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    duration_ms=duration_ms,
                    error=error[:500] if error else None,
                )
            )

    def get_llm_usage_summary(
        self,
        from_dt: datetime,
        to_dt: datetime,
        uid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return aggregated token usage between from_dt and to_dt.

        Returns a dict with keys:
          total_calls, total_tokens,
          by_call_type: list of {call_type, calls, total_tokens},
          by_model:     list of {model, calls, total_tokens}
        """
        from_dt = ensure_aware_datetime(from_dt) or utc_now()
        to_dt = ensure_aware_datetime(to_dt) or utc_now()
        with self.session_scope() as session:
            base_filter = and_(
                LLMUsage.called_at >= from_dt,
                LLMUsage.called_at <= to_dt,
            )
            if uid is not None:
                base_filter = and_(base_filter, LLMUsage.uid == uid)

            # Overall totals
            totals = session.execute(
                select(
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                ).where(base_filter)
            ).one()

            # Breakdown by call_type
            by_type_rows = session.execute(
                select(
                    LLMUsage.call_type,
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                )
                .where(base_filter)
                .group_by(LLMUsage.call_type)
                .order_by(desc(func.sum(LLMUsage.total_tokens)))
            ).all()

            # Breakdown by model
            by_model_rows = session.execute(
                select(
                    LLMUsage.model,
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                )
                .where(base_filter)
                .group_by(LLMUsage.model)
                .order_by(desc(func.sum(LLMUsage.total_tokens)))
            ).all()

        return {
            "total_calls": totals.calls,
            "total_tokens": totals.tokens,
            "by_call_type": [
                {"call_type": r.call_type, "calls": r.calls, "total_tokens": r.tokens} for r in by_type_rows
            ],
            "by_model": [
                {
                    "model": r.model or "unknown",
                    "calls": r.calls,
                    "total_tokens": r.tokens,
                }
                for r in by_model_rows
            ],
        }
