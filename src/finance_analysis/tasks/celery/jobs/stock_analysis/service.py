"""Business adapter used by the single-stock Celery task."""

from __future__ import annotations

from typing import Any, Dict, Optional

from finance_analysis.tasks.celery.jobs.message_payload import bot_message_from_payload


class StockAnalysisTaskService:
    def run(
        self,
        *,
        task_id: str,
        stock_code: str,
        report_type: str,
        force_refresh: bool,
        notify: bool,
        owner_uid: Optional[int],
        task_source: str,
        bot_message: Optional[Dict[str, Any]],
        save_context_snapshot: Optional[bool],
    ) -> Dict[str, Any]:
        if task_source == "bot":
            result = self._run_bot_analysis(
                task_id=task_id,
                stock_code=stock_code,
                report_type=report_type,
                bot_message=bot_message,
                save_context_snapshot=save_context_snapshot,
            )
        else:
            result = self._run_api_analysis(
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

    @staticmethod
    def _run_api_analysis(
        *,
        task_id: str,
        stock_code: str,
        report_type: str,
        force_refresh: bool,
        notify: bool,
        owner_uid: Optional[int],
    ) -> Dict[str, Any]:
        from finance_analysis.analysis.service import AnalysisService
        from finance_analysis.tasks.lifecycle import get_task_lifecycle_service

        service = AnalysisService()

        def on_progress(progress: int, message: str) -> None:
            get_task_lifecycle_service().mark_progress(task_id=task_id, progress=progress, message=message)

        result = service.analyze_stock(
            stock_code=stock_code,
            report_type=report_type,
            force_refresh=force_refresh,
            query_id=task_id,
            send_notification=notify,
            progress_callback=on_progress,
            owner_uid=owner_uid,
        )
        if result is None:
            raise RuntimeError(service.last_error or f"分析股票 {stock_code} 失败")
        return result

    @staticmethod
    def _run_bot_analysis(
        *,
        task_id: str,
        stock_code: str,
        report_type: str,
        bot_message: Optional[Dict[str, Any]],
        save_context_snapshot: Optional[bool],
    ) -> Dict[str, Any]:
        from finance_analysis.analysis.pipeline import StockAnalysisPipeline
        from finance_analysis.analysis.pipeline_config import get_pipeline_config
        from finance_analysis.reporting.types import ReportType

        pipeline = StockAnalysisPipeline(
            config=get_pipeline_config(),
            max_workers=1,
            source_message=bot_message_from_payload(bot_message),
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


__all__ = ["StockAnalysisTaskService"]
