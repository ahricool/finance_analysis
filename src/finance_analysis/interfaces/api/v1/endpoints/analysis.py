# -*- coding: utf-8 -*-
"""
===================================
股票分析接口
===================================

职责：
1. 提供 POST /api/v1/analysis/analyze 触发分析接口
2. 提供 GET /api/v1/analysis/status/{task_id} 查询任务状态接口
3. 提供 GET /api/v1/analysis/tasks 获取任务列表接口

特性：
- 异步任务队列：分析任务异步执行，不阻塞请求
- 防重复提交：相同股票代码正在分析时返回 409
"""

import logging
import re
from pathlib import Path
from typing import Optional, Union, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query, Body, Request
from fastapi.responses import JSONResponse

from finance_analysis.interfaces.api.deps import get_config_dep, get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    BatchTaskAcceptedResponse,
    BatchTaskAcceptedItem,
    BatchDuplicateTaskItem,
    TaskStatus,
    TaskInfo,
    TaskListResponse,
    DuplicateTaskErrorResponse,
    MarketReviewRequest,
    MarketReviewAccepted,
)
from finance_analysis.interfaces.api.v1.schemas.common import ErrorResponse
from finance_analysis.interfaces.api.v1.schemas.history import (
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
)
from finance_analysis.integrations.market_data.base import canonical_stock_code, normalize_stock_code
from finance_analysis.analysis.pipeline_config import PipelineConfig
from finance_analysis.market_review.lock import (
    market_review_lock_path,
)
from finance_analysis.reporting.config import get_report_config
from finance_analysis.reporting.localization import get_localized_stock_name, normalize_report_language
from finance_analysis.stocks.resolver import resolve_name_to_code
from finance_analysis.stocks.symbols import is_code_like
from finance_analysis.tasks.queue import (
    get_task_queue,
    DuplicateTaskError,
)
from finance_analysis.database.repositories.task_record import TaskRecordRepository
from finance_analysis.analysis.context_normalizer import (
    normalize_model_used,
    parse_json_field,
    extract_fundamental_detail_fields,
    extract_board_detail_fields,
)
from finance_analysis.core.time import utc_isoformat, utc_now

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_FREE_TEXT_RE = re.compile(r"^[A-Za-z0-9.*\-+\u3400-\u9fff\s]+$")


def _market_review_lock_path(config: PipelineConfig) -> Path:
    return market_review_lock_path(config)


def _compute_market_review_override_region(config: PipelineConfig) -> Optional[str]:
    if not getattr(config, "trading_day_check_enabled", True):
        return None

    try:
        from finance_analysis.market_review.trading_calendar import (
            get_open_markets_today,
            compute_effective_region,
        )

        open_markets = get_open_markets_today()
        return compute_effective_region(
            getattr(config, "market_review_region", "cn") or "cn",
            open_markets,
        )
    except Exception as exc:
        logger.warning("大盘复盘交易日过滤失败，按配置继续执行: %s", exc)
        return None


def _invalid_analysis_input_error() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": "validation_error",
            "message": "请输入有效的股票代码或股票名称",
        },
    )


def _is_obviously_invalid_analysis_input(text: str) -> bool:
    """Reject mixed alphanumeric noise and unsupported symbols early."""
    if not text or is_code_like(text):
        return False

    if not _SUPPORTED_FREE_TEXT_RE.fullmatch(text):
        return True

    has_letters = any(ch.isalpha() and ch.isascii() for ch in text)
    has_digits = any(ch.isdigit() for ch in text)
    return has_letters and has_digits


def _resolve_and_normalize_input(raw_value: str) -> str:
    """
    Resolve and normalize a stock input for analysis requests.

    Code-like values keep the existing canonical path.
    Non-code inputs must resolve to a known stock code. Obvious garbage
    input is rejected before expensive resolver and task-queue work.
    """
    text = (raw_value or "").strip()
    if not text:
        return ""

    if is_code_like(text):
        return canonical_stock_code(text)

    if _is_obviously_invalid_analysis_input(text):
        raise _invalid_analysis_input_error()

    resolved = resolve_name_to_code(text)
    if resolved:
        return canonical_stock_code(resolved)

    raise _invalid_analysis_input_error()


# ============================================================
# POST /analyze - 触发股票分析
# ============================================================

@router.post(
    "/analyze",
    response_model=AnalysisResultResponse,
    responses={
        200: {"description": "分析完成（同步模式）", "model": AnalysisResultResponse},
        202: {
            "description": "分析任务已接受（异步模式）",
            "model": Union[TaskAccepted, BatchTaskAcceptedResponse],
        },
        400: {"description": "请求参数错误", "model": ErrorResponse},
        409: {"description": "股票正在分析中，拒绝重复提交", "model": DuplicateTaskErrorResponse},
        500: {"description": "分析失败", "model": ErrorResponse},
    },
    summary="触发股票分析",
    description="启动 AI 智能分析任务，支持同步和异步模式。异步模式下相同股票代码不允许重复提交。"
)
def trigger_analysis(
        request: AnalyzeRequest,
        http_request: Request = None,
        config: PipelineConfig = Depends(get_config_dep)
) -> Union[AnalysisResultResponse, JSONResponse]:
    """
    触发股票分析
    
    启动 AI 智能分析任务，支持单只或多只股票批量分析
    
    流程：
    1. 校验请求参数
    2. 异步模式：检查重复 -> 提交任务队列 -> 返回 202
    3. 同步模式：直接执行分析 -> 返回 200
    
    Args:
        request: 分析请求参数
        config: 配置依赖
        
    Returns:
        AnalysisResultResponse: 分析结果（同步模式）
        TaskAccepted | BatchTaskAcceptedResponse: 任务已接受（异步模式，返回 202）
        
    Raises:
        HTTPException: 400 - 请求参数错误
        HTTPException: 409 - 股票正在分析中
        HTTPException: 500 - 分析失败
    """
    # 校验请求参数
    stock_codes = []
    if request.stock_code:
        stock_codes.append(request.stock_code)
    if request.stock_codes:
        stock_codes.extend(request.stock_codes)

    if not stock_codes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "必须提供 stock_code 或 stock_codes 参数"
            }
        )

    # Normalize and de-duplicate inputs while preserving compatibility.
    resolved = [_resolve_and_normalize_input(c) for c in stock_codes]
    
    seen = set()
    unique_codes = []
    for code in resolved:
        if not code:
            continue
        # Use normalize_stock_code to ensure '600519' and '600519.SH' are merged
        norm = normalize_stock_code(code)
        if norm not in seen:
            seen.add(norm)
            unique_codes.append(code)
    
    stock_codes = unique_codes

    # Limit the number of stocks in a single request to prevent DoS
    MAX_BATCH_SIZE = 50
    if len(stock_codes) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": f"单次分析请求最多支持 {MAX_BATCH_SIZE} 只股票"
            }
        )

    if not stock_codes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "股票代码不能为空或仅包含空白字符"
            }
        )

    # Sync mode only supports single-stock analysis.
    if not request.async_mode:
        if len(stock_codes) > 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_error",
                    "message": "同步模式仅支持单只股票分析，请使用 async_mode=true 进行批量分析"
                }
            )
        return _handle_sync_analysis(
            stock_codes[0],
            request,
            get_effective_uid(http_request) if http_request is not None else None,
        )

    # Async mode submits one task per stock.
    return _handle_async_analysis_batch(
        stock_codes,
        request,
        get_effective_uid(http_request) if http_request is not None else None,
    )


def _handle_async_analysis_batch(
    stock_codes: list,
    request: AnalyzeRequest,
    owner_uid: Optional[int],
) -> JSONResponse:
    """
    Handle asynchronous analysis requests, including batch submission.
    """
    task_queue = get_task_queue()
    
    # Preserve metadata for single-stock requests. For batch requests,
    # only carry through metadata that semantically applies to the whole
    # batch, such as import/image source tracking.
    is_single = len(stock_codes) == 1
    preserve_batch_metadata = request.selection_source in {"import", "image"}

    stock_name = request.stock_name if is_single else None
    original_query = request.original_query if (is_single or preserve_batch_metadata) else None
    selection_source = request.selection_source if (is_single or preserve_batch_metadata) else None
    submit_kwargs = dict(
        stock_codes=stock_codes,
        stock_name=stock_name,
        original_query=original_query,
        selection_source=selection_source,
        report_type=request.report_type,
        force_refresh=request.force_refresh,
        notify=True,
    )
    if owner_uid is not None:
        submit_kwargs["owner_uid"] = owner_uid

    accepted_tasks, duplicate_errors = task_queue.submit_tasks_batch(**submit_kwargs)

    accepted = [
        BatchTaskAcceptedItem(
            task_id=task.task_id,
            stock_code=task.stock_code,
            status="pending",
            message=f"分析任务已加入队列: {task.stock_code}",
        )
        for task in accepted_tasks
    ]
    duplicates = [
        BatchDuplicateTaskItem(
            stock_code=dup.stock_code,
            existing_task_id=dup.existing_task_id,
            message=str(dup),
        )
        for dup in duplicate_errors
    ]
    
    # 单只股票且被拒绝：保持 409 兼容性
    if len(stock_codes) == 1 and duplicates:
        dup = duplicates[0]
        error_response = DuplicateTaskErrorResponse(
            error="duplicate_task",
            message=dup.message,
            stock_code=dup.stock_code,
            existing_task_id=dup.existing_task_id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response.model_dump()
        )
    
    # 单只股票成功：保持原有响应格式兼容性
    if len(stock_codes) == 1 and accepted:
        task_accepted = TaskAccepted(
            task_id=accepted[0].task_id,
            status="pending",
            message=accepted[0].message,
        )
        return JSONResponse(
            status_code=202,
            content=task_accepted.model_dump()
        )
    
    # 批量：返回汇总结果
    batch_response = BatchTaskAcceptedResponse(
        accepted=accepted,
        duplicates=duplicates,
        message=f"已提交 {len(accepted)} 个任务，{len(duplicates)} 个重复跳过",
    )
    return JSONResponse(
        status_code=202,
        content=batch_response.model_dump()
    )


def _handle_sync_analysis(
    stock_code: str,
    request: AnalyzeRequest,
    owner_uid: Optional[int] = None,
) -> AnalysisResultResponse:
    """
    处理同步分析请求
    
    直接执行分析，等待完成后返回结果
    """
    import uuid
    from finance_analysis.analysis.service import AnalysisService
    
    query_id = uuid.uuid4().hex
    
    try:
        service = AnalysisService()
        result = service.analyze_stock(
            stock_code=stock_code,
            report_type=request.report_type,
            force_refresh=request.force_refresh,
            query_id=query_id,
            send_notification=True,
            owner_uid=owner_uid,
        )

        if result is None:
            error_message = service.last_error or f"分析股票 {stock_code} 失败"
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "analysis_failed",
                    "message": error_message,
                }
            )

        # 构建报告结构
        report_data = result.get("report", {})
        context_snapshot, fundamental_snapshot = _load_sync_fundamental_sources(
            query_id=query_id,
            stock_code=result.get("stock_code", stock_code),
        )
        report = _build_analysis_report(
            report_data,
            query_id,
            stock_code,
            result.get("stock_name"),
            context_snapshot=context_snapshot,
            fallback_fundamental_payload=fundamental_snapshot,
        )

        return AnalysisResultResponse(
            query_id=query_id,
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            report=report.model_dump() if report else None,
            created_at=utc_isoformat(utc_now())
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"分析过程发生错误: {str(e)}"
            }
        )


# ============================================================
# POST /market-review - 触发大盘复盘
# ============================================================

@router.post(
    "/market-review",
    response_model=MarketReviewAccepted,
    status_code=202,
    responses={
        202: {"description": "大盘复盘任务已接受", "model": MarketReviewAccepted},
        409: {"description": "大盘复盘正在执行", "model": ErrorResponse},
        500: {"description": "提交失败", "model": ErrorResponse},
    },
    summary="触发大盘复盘",
    description="提交一个后台大盘复盘任务，复用 CLI 的大盘复盘链路并保存报告。接口内部仅提供进程内/单机防重，如多实例（多 Worker/多容器）部署，需结合外部幂等机制避免重复触发。",
)
def trigger_market_review(
    request: Optional[MarketReviewRequest] = Body(None),
    config: PipelineConfig = Depends(get_config_dep),
) -> MarketReviewAccepted:
    """Trigger market review from Web/API without blocking the request."""
    request = request or MarketReviewRequest()

    override_region = _compute_market_review_override_region(config)
    if override_region == "":
        return MarketReviewAccepted(
            status="accepted",
            message="今日大盘复盘相关市场均为非交易日，已跳过大盘复盘",
            send_notification=True,
        )

    try:
        task = get_task_queue().submit_market_review(
            send_notification=True,
            override_region=override_region,
        )
    except DuplicateTaskError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_market_review",
                "message": "大盘复盘正在执行中，请稍后再试",
            },
        )
    except Exception:
        raise

    return MarketReviewAccepted(
        status="accepted",
        message="大盘复盘任务已提交，完成后会保存报告并按配置推送通知",
        send_notification=True,
        task_id=task.task_id,
    )


# ============================================================
# GET /tasks - 获取任务列表
# ============================================================

@router.get(
    "/tasks",
    response_model=TaskListResponse,
    responses={
        200: {"description": "任务列表"},
    },
    summary="获取分析任务列表",
    description="获取当前所有分析任务，可按状态筛选"
)
def get_task_list(
    status: Optional[str] = Query(
        None,
        description="筛选状态：pending, processing, completed, failed（支持逗号分隔多个）"
    ),
    limit: int = Query(20, description="返回数量限制", ge=1, le=100),
) -> TaskListResponse:
    """
    获取分析任务列表
    
    Args:
        status: 状态筛选（可选）
        limit: 返回数量限制
        
    Returns:
        TaskListResponse: 任务列表响应
    """
    status_list = [s.strip().lower() for s in status.split(",")] if status else []
    repository = TaskRecordRepository()
    records = repository.list_tasks(limit=limit, statuses=status_list or None)
    task_infos = [_task_record_to_task_info(record) for record in records]
    stats = repository.count_by_status()
    total = repository.count_tasks(statuses=status_list or None)
    
    return TaskListResponse(
        total=total,
        pending=stats.get("pending", 0),
        processing=stats.get("processing", 0),
        tasks=task_infos,
    )


def _task_record_to_task_info(record: Any) -> TaskInfo:
    payload = parse_json_field(getattr(record, "payload", None)) or {}
    kwargs = payload.get("kwargs") if isinstance(payload, dict) else {}
    if not isinstance(kwargs, dict):
        kwargs = {}
    stock_code = (
        kwargs.get("stock_code")
        or ("market_review" if record.task_type == "market_review" else None)
        or record.task_type
    )
    completed_at = getattr(record, "finished_at", None)
    return TaskInfo(
        task_id=record.task_id,
        stock_code=str(stock_code or record.task_type),
        stock_name=record.task_name,
        status=record.status,
        progress=int(record.progress or 0),
        message=record.message,
        report_type=str(kwargs.get("report_type") or "detailed"),
        created_at=utc_isoformat(record.created_at) or utc_isoformat(utc_now()),
        started_at=utc_isoformat(record.started_at),
        completed_at=utc_isoformat(completed_at),
        error=(record.error[:200] if record.error else None),
        original_query=kwargs.get("original_query"),
        selection_source=kwargs.get("selection_source"),
    )


# ============================================================
# GET /status/{task_id} - 查询单个任务状态
# ============================================================

@router.get(
    "/status/{task_id}",
    response_model=TaskStatus,
    responses={
        200: {"description": "任务状态"},
        404: {"description": "任务不存在", "model": ErrorResponse},
    },
    summary="查询分析任务状态",
    description="根据 task_id 查询单个任务的状态"
)
def get_analysis_status(task_id: str, http_request: Request = None) -> TaskStatus:
    """
    查询分析任务状态
    
    从 PostgreSQL 任务记录查询状态；完成的股票分析可继续回补分析历史报告。
    
    Args:
        task_id: 任务 ID
        
    Returns:
        TaskStatus: 任务状态信息
        
    Raises:
        HTTPException: 404 - 任务不存在
    """
    try:
        task_record = TaskRecordRepository().get_by_task_id(task_id)
        if task_record is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"任务 {task_id} 不存在",
                },
            )

        from finance_analysis.database import DatabaseManager
        db = DatabaseManager.get_instance()
        history_kwargs: Dict[str, Any] = {"query_id": task_id, "limit": 1}
        if http_request is not None:
            history_kwargs["uid"] = get_effective_uid(http_request)
        records = db.get_analysis_history(**history_kwargs)

        if records:
            record = records[0]
            raw_result = parse_json_field(record.raw_result)
            model_used = normalize_model_used(
                (raw_result or {}).get("model_used") if isinstance(raw_result, dict) else None
            )
            report_language = normalize_report_language(
                (raw_result or {}).get("report_language") if isinstance(raw_result, dict) else None
            )
            stock_name = get_localized_stock_name(record.name, record.code, report_language)

            # Extract current_price / change_pct from context_snapshot
            current_price = None
            change_pct = None
            context_snapshot = parse_json_field(getattr(record, 'context_snapshot', None))
            if context_snapshot and isinstance(context_snapshot, dict):
                enhanced_context = context_snapshot.get('enhanced_context') or {}
                realtime = enhanced_context.get('realtime') or {}
                current_price = realtime.get('price')
                change_pct = realtime.get('change_pct')
                realtime_quote_raw = context_snapshot.get('realtime_quote_raw') or {}
                if current_price is None:
                    current_price = realtime_quote_raw.get('price')
                if change_pct is None:
                    change_pct = realtime_quote_raw.get('change_pct')
                if change_pct is None:
                    change_pct = realtime_quote_raw.get('pct_chg')

            # Build report from DB record so completed tasks return real data
            report_dict = AnalysisReport(
                meta=ReportMeta(
                    id=record.id,
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=stock_name,
                    report_type=getattr(record, 'report_type', None),
                    report_language=report_language,
                    created_at=utc_isoformat(record.created_at),
                    model_used=model_used,
                    current_price=current_price,
                    change_pct=change_pct,
                ),
                summary=ReportSummary(
                    sentiment_score=record.sentiment_score,
                    operation_advice=record.operation_advice,
                    trend_prediction=record.trend_prediction,
                    analysis_summary=record.analysis_summary,
                ),
                strategy=ReportStrategy(
                    ideal_buy=_stringify_report_strategy_value(getattr(record, 'ideal_buy', None)),
                    secondary_buy=_stringify_report_strategy_value(getattr(record, 'secondary_buy', None)),
                    stop_loss=_stringify_report_strategy_value(getattr(record, 'stop_loss', None)),
                    take_profit=_stringify_report_strategy_value(getattr(record, 'take_profit', None)),
                ),
            ).model_dump()
            task_status = task_record.status if isinstance(task_record.status, str) else "completed"
            return TaskStatus(
                task_id=task_id,
                status=task_status,
                progress=100,
                result=AnalysisResultResponse(
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=stock_name,
                    report=report_dict,
                    created_at=utc_isoformat(record.created_at) or utc_isoformat(utc_now())
                ),
                error=None
            )

        result_payload = parse_json_field(getattr(task_record, "result", None))
        payload = parse_json_field(getattr(task_record, "payload", None)) or {}
        kwargs = payload.get("kwargs") if isinstance(payload, dict) else payload
        if not isinstance(kwargs, dict):
            kwargs = {}
        market_review_report = None
        if task_record.task_type == "market_review" and isinstance(result_payload, dict):
            report_text = result_payload.get("result")
            if isinstance(report_text, str) and report_text.strip():
                market_review_report = report_text
        return TaskStatus(
            task_id=task_id,
            status=task_record.status,
            progress=int(task_record.progress or 0),
            result=None,
            market_review_report=market_review_report,
            error=(task_record.error[:200] if task_record.error else None),
            stock_name=task_record.task_name,
            original_query=kwargs.get("original_query"),
            selection_source=kwargs.get("selection_source"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询任务状态失败: {str(e)}"
            }
        )

# ============================================================
# 辅助函数
# ============================================================

def _load_sync_fundamental_sources(
    query_id: str,
    stock_code: str,
) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    Load context_snapshot and fallback fundamental snapshot for sync analyze response.
    """
    try:
        from finance_analysis.database import DatabaseManager

        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=query_id, code=stock_code, limit=1)
        context_snapshot = None
        if records:
            context_snapshot = parse_json_field(getattr(records[0], "context_snapshot", None))

        fallback_fundamental = db.get_latest_fundamental_snapshot(
            query_id=query_id,
            code=stock_code,
        )
        return context_snapshot, fallback_fundamental
    except Exception as e:
        logger.debug(
            "load sync fundamental sources failed (fail-open): query_id=%s stock_code=%s err=%s",
            query_id,
            stock_code,
            e,
        )
        return None, None


def _stringify_report_strategy_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _build_analysis_report(
        report_data: Dict[str, Any],
        query_id: str,
        stock_code: str,
        stock_name: Optional[str] = None,
        context_snapshot: Optional[Any] = None,
        fallback_fundamental_payload: Optional[Dict[str, Any]] = None,
) -> AnalysisReport:
    """
    构建符合 API 规范的分析报告
    
    Args:
        report_data: 原始报告数据
        query_id: 查询 ID
        stock_code: 股票代码
        stock_name: 股票名称
        context_snapshot: 上下文快照（可选）
        fallback_fundamental_payload: 基本面快照 payload（可选）
        
    Returns:
        AnalysisReport: 结构化的分析报告
    """
    meta_data = report_data.get("meta", {})
    summary_data = report_data.get("summary", {})
    strategy_data = report_data.get("strategy", {})
    details_data = report_data.get("details", {})
    report_language = normalize_report_language(
        meta_data.get("report_language")
        or (context_snapshot or {}).get("report_language")
        or get_report_config().report_language
    )
    localized_stock_name = get_localized_stock_name(
        meta_data.get("stock_name", stock_name),
        meta_data.get("stock_code", stock_code),
        report_language,
    )

    meta = ReportMeta(
        query_id=meta_data.get("query_id", query_id),
        stock_code=meta_data.get("stock_code", stock_code),
        stock_name=localized_stock_name,
        report_type=meta_data.get("report_type", "detailed"),
        report_language=report_language,
        created_at=meta_data.get("created_at", utc_isoformat(utc_now())),
        current_price=meta_data.get("current_price"),
        change_pct=meta_data.get("change_pct"),
        model_used=normalize_model_used(meta_data.get("model_used")),
    )

    summary = ReportSummary(
        analysis_summary=summary_data.get("analysis_summary"),
        operation_advice=summary_data.get("operation_advice"),
        trend_prediction=summary_data.get("trend_prediction"),
        sentiment_score=summary_data.get("sentiment_score"),
        sentiment_label=summary_data.get("sentiment_label")
    )

    strategy = None
    if strategy_data:
        strategy = ReportStrategy(
            ideal_buy=_stringify_report_strategy_value(strategy_data.get("ideal_buy")),
            secondary_buy=_stringify_report_strategy_value(strategy_data.get("secondary_buy")),
            stop_loss=_stringify_report_strategy_value(strategy_data.get("stop_loss")),
            take_profit=_stringify_report_strategy_value(strategy_data.get("take_profit"))
        )

    extracted_fundamental = extract_fundamental_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    extracted_boards = extract_board_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    details = None
    has_board_details = bool(extracted_boards.get("belong_boards")) or extracted_boards.get("sector_rankings") is not None
    if details_data or any(extracted_fundamental.values()) or has_board_details or context_snapshot is not None:
        details = ReportDetails(
            news_content=details_data.get("news_summary") or details_data.get("news_content"),
            raw_result=details_data,
            context_snapshot=context_snapshot,
            financial_report=extracted_fundamental.get("financial_report"),
            dividend_metrics=extracted_fundamental.get("dividend_metrics"),
            belong_boards=extracted_boards.get("belong_boards"),
            sector_rankings=extracted_boards.get("sector_rankings"),
        )

    return AnalysisReport(
        meta=meta,
        summary=summary,
        strategy=strategy,
        details=details
    )
