"""Business adapter used by the market-review Celery task."""

from __future__ import annotations

from typing import Any, Dict, Optional

from finance_analysis.tasks.celery.jobs.message_payload import bot_message_from_payload


class MarketReviewTaskService:
    def run(
        self,
        *,
        send_notification: bool,
        override_region: Optional[str],
        bot_message: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.market_review.lock import release_market_review_lock, try_acquire_market_review_lock
        from finance_analysis.market_review.runtime import build_market_review_runtime
        from finance_analysis.market_review.service import run_market_review

        config = get_pipeline_config()
        lock_token = try_acquire_market_review_lock(config)
        if lock_token is None:
            raise RuntimeError("大盘复盘正在执行中")
        try:
            notifier, analyzer, search_service = build_market_review_runtime(
                config,
                source_message=bot_message_from_payload(bot_message),
            )
            report = run_market_review(
                notifier=notifier,
                analyzer=analyzer,
                search_service=search_service,
                send_notification=send_notification,
                override_region=override_region,
            )
            if not report:
                raise RuntimeError("大盘复盘未返回可持久化报告")
            return {"result": report}
        finally:
            release_market_review_lock(lock_token)


__all__ = ["MarketReviewTaskService"]
