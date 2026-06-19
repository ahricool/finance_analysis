# -*- coding: utf-8 -*-
"""Business Celery tasks for stock analysis and market review."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bot.models import BotMessage, ChatType
from src.celery_app.app import celery_app
from src.tasks.lifecycle import track_task

logger = logging.getLogger(__name__)


def _bot_message_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[BotMessage]:
    if not payload:
        return None
    timestamp = payload.get("timestamp")
    parsed_timestamp = datetime.now()
    if isinstance(timestamp, str):
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            parsed_timestamp = datetime.now()
    return BotMessage(
        platform=str(payload.get("platform") or ""),
        message_id=str(payload.get("message_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        user_name=str(payload.get("user_name") or ""),
        chat_id=str(payload.get("chat_id") or ""),
        chat_type=ChatType(payload.get("chat_type") or ChatType.UNKNOWN.value),
        content=str(payload.get("content") or ""),
        raw_content=str(payload.get("raw_content") or ""),
        mentioned=bool(payload.get("mentioned") or False),
        mentions=list(payload.get("mentions") or []),
        timestamp=parsed_timestamp,
        raw_data=dict(payload.get("raw_data") or {}),
    )


@celery_app.task(name="analysis.run_stock_analysis")
@track_task(
    task_type="stock_analysis",
    task_name="股票分析",
    source="celery_manual",
    uid_getter=lambda **kwargs: kwargs.get("owner_uid"),
    task_name_getter=lambda **kwargs: f"股票分析 {kwargs.get('stock_code') or ''}".strip(),
    success_message="分析完成",
)
def run_stock_analysis(
    *,
    task_id: str,
    stock_code: str,
    report_type: str = "detailed",
    force_refresh: bool = False,
    notify: bool = True,
    owner_uid: Optional[int] = None,
    task_source: str = "api",
    bot_message: Optional[Dict[str, Any]] = None,
    save_context_snapshot: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Run one stock-analysis task inside a Celery worker."""
    if task_source == "bot":
        result = _run_bot_stock_analysis(
            task_id=task_id,
            stock_code=stock_code,
            report_type=report_type,
            bot_message=bot_message,
            save_context_snapshot=save_context_snapshot,
        )
    else:
        result = _run_api_stock_analysis(
            task_id=task_id,
            stock_code=stock_code,
            report_type=report_type,
            force_refresh=force_refresh,
            notify=notify,
            owner_uid=owner_uid,
        )

    if not result:
        raise RuntimeError("分析返回空结果")
    return result


def _run_api_stock_analysis(
    *,
    task_id: str,
    stock_code: str,
    report_type: str,
    force_refresh: bool,
    notify: bool,
    owner_uid: Optional[int],
) -> Optional[Dict[str, Any]]:
    from src.services.analysis_service import AnalysisService
    from src.tasks.queue import get_task_queue

    queue = get_task_queue()
    service = AnalysisService()

    def _on_progress(progress: int, message: str) -> None:
        queue.update_task_progress(task_id, progress, message)

    result = service.analyze_stock(
        stock_code=stock_code,
        report_type=report_type,
        force_refresh=force_refresh,
        query_id=task_id,
        send_notification=notify,
        progress_callback=_on_progress,
        owner_uid=owner_uid,
    )
    if result is None:
        raise RuntimeError(service.last_error or f"分析股票 {stock_code} 失败")
    return result


def _run_bot_stock_analysis(
    *,
    task_id: str,
    stock_code: str,
    report_type: str,
    bot_message: Optional[Dict[str, Any]],
    save_context_snapshot: Optional[bool],
) -> Optional[Dict[str, Any]]:
    from src.config import get_config
    from src.core.pipeline import StockAnalysisPipeline
    from src.enums import ReportType

    source_message = _bot_message_from_payload(bot_message)
    pipeline = StockAnalysisPipeline(
        config=get_config(),
        max_workers=1,
        source_message=source_message,
        query_id=task_id,
        query_source="bot",
        save_context_snapshot=save_context_snapshot,
    )
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=True,
        report_type=ReportType.from_str(report_type),
    )
    if result is None:
        raise RuntimeError(f"分析股票 {stock_code} 返回空结果")
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "error_message", None) or f"分析股票 {stock_code} 失败")
    return {
        "code": result.code,
        "name": result.name,
        "stock_code": result.code,
        "stock_name": result.name,
        "sentiment_score": result.sentiment_score,
        "operation_advice": result.operation_advice,
        "trend_prediction": result.trend_prediction,
        "analysis_summary": result.analysis_summary,
    }


@celery_app.task(name="analysis.run_market_review")
@track_task(
    task_type="market_review",
    task_name="大盘复盘",
    source="celery_manual",
    record_result=True,
    success_message="任务执行完成",
)
def run_market_review(
    *,
    task_id: str,
    send_notification: bool,
    override_region: Optional[str] = None,
    bot_message: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Run market review inside a Celery worker."""
    from src.config import get_config
    from src.core.market_review import run_market_review as run_market_review_pipeline
    from src.core.market_review_lock import release_market_review_lock, try_acquire_market_review_lock
    from src.core.market_review_runtime import build_market_review_runtime

    config = get_config()
    lock_token = try_acquire_market_review_lock(config)
    if lock_token is None:
        raise RuntimeError("大盘复盘正在执行中")

    try:
        notifier, analyzer, search_service = build_market_review_runtime(
            config,
            source_message=_bot_message_from_payload(bot_message),
        )
        report = run_market_review_pipeline(
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


@celery_app.task(name="analysis.run_batch_analysis")
@track_task(
    task_type="batch_analysis",
    task_name="批量分析",
    source="celery_manual",
    record_result=True,
    success_message="批量分析完成",
)
def run_batch_analysis(
    *,
    task_id: str,
    stock_codes: list[str],
    bot_message: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Run Bot batch analysis inside a Celery worker."""
    from src.config import get_config
    from src.core.pipeline import StockAnalysisPipeline

    pipeline = StockAnalysisPipeline(
        config=get_config(),
        source_message=_bot_message_from_payload(bot_message),
        query_id=task_id,
        query_source="bot",
    )
    results = pipeline.run(
        stock_codes=stock_codes,
        dry_run=False,
        send_notification=True,
    )
    return {"result": {"success_count": len(results), "stock_count": len(stock_codes)}}
