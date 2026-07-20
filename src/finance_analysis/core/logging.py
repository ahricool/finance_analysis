# -*- coding: utf-8 -*-
"""
===================================
日志配置模块 - 统一的日志系统初始化
===================================

职责：
1. 提供统一的日志格式和配置常量
2. 支持控制台 + 文件（常规/调试）三层日志输出
3. 自动降低第三方库日志级别
"""

import logging
import os
import re
import sys
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from logging import FileHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from finance_analysis.core.paths import (
    PROJECT_ROOT,
    get_log_app_dir,
    get_log_celery_dir,
    get_log_dir,
    get_log_scheduler_dir,
)

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(pathname)s:%(lineno)d | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
SERVICE_LOG_DIRS = {
    "server": "app",
    "app": "app",
    "celery": "celery",
}
DEFAULT_APP_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_APP_LOG_BACKUP_COUNT = 5
DEFAULT_DEBUG_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_DEBUG_LOG_BACKUP_COUNT = 3
_ALLOWED_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_DEFAULT_LITELLM_LOG_LEVEL = "WARNING"
_TASK_HANDLER_LOCK = threading.RLock()
_TASK_RECORD_FACTORY_LOCK = threading.RLock()
_TASK_RECORD_FACTORY_INSTALLED = False
_TASK_ID_CONTEXT: ContextVar[Optional[str]] = ContextVar("finance_task_id", default=None)
_TASK_NAME_CONTEXT: ContextVar[Optional[str]] = ContextVar("finance_task_name", default=None)
_SAFE_LOG_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class RelativePathFormatter(logging.Formatter):
    """自定义 Formatter，输出相对路径而非绝对路径"""

    def __init__(self, fmt=None, datefmt=None, relative_to=None):
        super().__init__(fmt, datefmt)
        self.relative_to = Path(relative_to) if relative_to else Path.cwd()

    def format(self, record):
        # 将绝对路径转为相对路径
        try:
            record.pathname = str(Path(record.pathname).relative_to(self.relative_to))
        except ValueError:
            # 如果无法转换为相对路径，保持原样
            pass
        return super().format(record)


# 默认需要降低日志级别的第三方库
DEFAULT_QUIET_LOGGERS = [
    "urllib3",
    "sqlalchemy",
    "google",
    "httpx",
]

# Third-party libraries whose INFO diagnostics are useful, but whose DEBUG
# output can overwhelm per-task logs and may include low-level request details.
DEFAULT_INFO_LOGGERS = [
    "yfinance",
    "akshare",
    "efinance",
    "longbridge",
    "peewee",
    "curl_cffi",
]

LITELLM_LOGGERS = [
    "LiteLLM",
    "LiteLLM Router",
    "LiteLLM Proxy",
    "litellm",
]


def _resolve_litellm_log_level(raw_level: Optional[str] = None) -> Tuple[int, Optional[str]]:
    """Resolve LiteLLM logger level from env, returning invalid raw value if any."""
    if raw_level is None:
        raw_level = os.getenv("LITELLM_LOG_LEVEL", "")

    normalized = (raw_level or "").strip().upper()
    if not normalized:
        normalized = _DEFAULT_LITELLM_LOG_LEVEL

    level = _ALLOWED_LOG_LEVELS.get(normalized)
    if level is None:
        return _ALLOWED_LOG_LEVELS[_DEFAULT_LITELLM_LOG_LEVEL], raw_level
    return level, None


def _resolve_log_level(raw_level: Optional[str], default: int = logging.INFO) -> int:
    """Resolve a logging level name or number with a conservative fallback."""
    if raw_level is None:
        return default
    normalized = str(raw_level).strip().upper()
    if not normalized:
        return default
    if normalized.isdigit():
        return int(normalized)
    return _ALLOWED_LOG_LEVELS.get(normalized, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def get_log_base_dir(log_base_dir: Optional[str] = None) -> Path:
    """Return the root log directory shared by all backend logging helpers."""
    if log_base_dir:
        return Path(log_base_dir).expanduser()
    return get_log_dir()


def get_service_log_dir(service: str, log_base_dir: Optional[str] = None) -> Path:
    """Resolve a backend service log directory under ``data/logs``."""
    service_key = (service or "server").strip().lower()
    subdir = SERVICE_LOG_DIRS.get(service_key, service_key)
    return get_log_base_dir(log_base_dir) / subdir


def get_task_log_dir(*, celery: bool = False, log_base_dir: Optional[str] = None) -> Path:
    """Resolve the directory for in-process scheduler or Celery task log files."""
    if celery:
        return get_log_celery_dir() if log_base_dir is None else get_log_base_dir(log_base_dir) / "celery"
    if log_base_dir is None:
        return get_log_scheduler_dir()
    return get_log_base_dir(log_base_dir) / "scheduler"


def _sanitize_log_file_stem(name: str) -> str:
    stem = _SAFE_LOG_NAME_RE.sub("_", str(name or "").strip()).strip("._-")
    return stem[:120] or "task"


def get_task_log_file(
    task_name: str,
    task_id: str,
    *,
    celery: bool = False,
    log_base_dir: Optional[str] = None,
) -> Path:
    """Resolve the per-run task log file."""
    file_stem = f"{_sanitize_log_file_stem(task_name)}_{_sanitize_log_file_stem(task_id)}"
    return get_task_log_dir(celery=celery, log_base_dir=log_base_dir) / f"{file_stem}.log"


class _TaskLogFilter(logging.Filter):
    """Allow only records emitted from the matching task context."""

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "finance_task_id", None) == self.task_id


def _install_task_record_factory() -> None:
    """Attach task context fields to every LogRecord exactly once."""
    global _TASK_RECORD_FACTORY_INSTALLED
    if _TASK_RECORD_FACTORY_INSTALLED:
        return
    with _TASK_RECORD_FACTORY_LOCK:
        if _TASK_RECORD_FACTORY_INSTALLED:
            return
        previous_factory = logging.getLogRecordFactory()

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous_factory(*args, **kwargs)
            record.finance_task_id = _TASK_ID_CONTEXT.get()
            record.finance_task_name = _TASK_NAME_CONTEXT.get()
            return record

        logging.setLogRecordFactory(record_factory)
        _TASK_RECORD_FACTORY_INSTALLED = True


def setup_logging(
    log_prefix: str = "app",
    log_dir: Optional[str] = None,
    console_level: Optional[int] = None,
    debug: bool = False,
    extra_quiet_loggers: Optional[List[str]] = None,
    service: Optional[str] = None,
) -> None:
    """
    统一的日志系统初始化

    配置三层日志输出：
    1. 控制台：根据 debug 参数或 console_level 设置级别
    2. 常规日志文件：INFO 级别，10MB 轮转，保留 5 个备份
    3. 调试日志文件：DEBUG 级别，50MB 轮转，保留 3 个备份

    Args:
        log_prefix: 日志文件名前缀（如 "api_server" -> api_server_20240101.log）
        log_dir: 日志文件目录，默认 data/logs/app；传入 service 时默认使用 data/logs/{service}
        console_level: 控制台日志级别（可选，优先于 debug 参数）
        debug: 是否启用调试模式（控制台输出 DEBUG 级别）
        extra_quiet_loggers: 额外需要降低日志级别的第三方库列表
        service: 后端服务名（server/celery），用于统一解析日志目录
    """
    # 确定控制台日志级别
    if console_level is not None:
        level = console_level
    else:
        level = logging.DEBUG if debug else _resolve_log_level(os.getenv("LOG_LEVEL"), logging.INFO)

    # 创建日志目录
    if log_dir is None:
        log_path = get_service_log_dir(service) if service else get_log_app_dir()
    else:
        log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 日志文件路径（按日期分文件）
    today_str = datetime.now().strftime("%Y%m%d")
    log_file = log_path / f"{log_prefix}_{today_str}.log"
    debug_log_file = log_path / f"{log_prefix}_debug_{today_str}.log"

    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 根 logger 设为 DEBUG，由 handler 控制输出级别

    # 清除已有 handler，避免重复添加
    if root_logger.handlers:
        root_logger.handlers.clear()
    # 创建相对路径 Formatter（相对于项目根目录）
    project_root = PROJECT_ROOT
    rel_formatter = RelativePathFormatter(LOG_FORMAT, LOG_DATE_FORMAT, relative_to=project_root)
    # Handler 1: 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(rel_formatter)
    console_handler._finance_app_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(console_handler)

    # Handler 2: 常规日志文件（INFO 级别，10MB 轮转）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_env_int("LOG_MAX_BYTES", DEFAULT_APP_LOG_MAX_BYTES),
        backupCount=_env_int("LOG_BACKUP_COUNT", DEFAULT_APP_LOG_BACKUP_COUNT),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(rel_formatter)
    file_handler._finance_app_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(file_handler)

    # Handler 3: 调试日志文件（DEBUG 级别，包含所有详细信息）
    debug_handler = RotatingFileHandler(
        debug_log_file,
        maxBytes=_env_int("DEBUG_LOG_MAX_BYTES", DEFAULT_DEBUG_LOG_MAX_BYTES),
        backupCount=_env_int("DEBUG_LOG_BACKUP_COUNT", DEFAULT_DEBUG_LOG_BACKUP_COUNT),
        encoding="utf-8",
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(rel_formatter)
    debug_handler._finance_app_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(debug_handler)

    # 降低第三方库的日志级别
    quiet_loggers = DEFAULT_QUIET_LOGGERS.copy()
    if extra_quiet_loggers:
        quiet_loggers.extend(extra_quiet_loggers)

    for logger_name in quiet_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    for logger_name in DEFAULT_INFO_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.INFO)

    litellm_level, invalid_litellm_level = _resolve_litellm_log_level()
    for logger_name in LITELLM_LOGGERS:
        logging.getLogger(logger_name).setLevel(litellm_level)

    # 输出初始化完成信息（使用相对路径）
    try:
        rel_log_path = log_path.resolve().relative_to(project_root)
    except ValueError:
        rel_log_path = log_path

    try:
        rel_log_file = log_file.resolve().relative_to(project_root)
    except ValueError:
        rel_log_file = log_file

    try:
        rel_debug_log_file = debug_log_file.resolve().relative_to(project_root)
    except ValueError:
        rel_debug_log_file = debug_log_file

    logging.info(f"日志系统初始化完成，日志目录: {rel_log_path}")
    logging.info(f"常规日志: {rel_log_file}")
    logging.info(f"调试日志: {rel_debug_log_file}")
    if invalid_litellm_level is not None:
        logging.warning(
            "LITELLM_LOG_LEVEL=%r 无效，已回退为 %s；可选值：%s",
            invalid_litellm_level,
            _DEFAULT_LITELLM_LOG_LEVEL,
            ", ".join(_ALLOWED_LOG_LEVELS),
        )


def setup_backend_logging(
    service: str = "server",
    *,
    log_prefix: Optional[str] = None,
    console_level: Optional[int] = None,
    debug: Optional[bool] = None,
    extra_quiet_loggers: Optional[List[str]] = None,
    log_base_dir: Optional[str] = None,
) -> None:
    """Initialize logging for a backend process using the standard directory layout."""
    service_key = (service or "server").strip().lower()
    service_log_dir = get_service_log_dir(service_key, log_base_dir)
    setup_logging(
        log_prefix=log_prefix or service_key,
        log_dir=str(service_log_dir),
        console_level=console_level,
        debug=(os.getenv("DEBUG", "false").lower() == "true") if debug is None else debug,
        extra_quiet_loggers=extra_quiet_loggers,
        service=service_key,
    )


def ensure_backend_logging(service: str = "server", **kwargs: Any) -> None:
    """Initialize backend logging only when the process has not been configured yet."""
    root_logger = logging.getLogger()
    if any(getattr(handler, "_finance_app_handler", False) for handler in root_logger.handlers):
        return
    setup_backend_logging(service=service, **kwargs)


@contextmanager
def task_logging_context(
    task_name: str,
    *,
    task_id: Optional[str] = None,
    celery: bool = False,
    log_base_dir: Optional[str] = None,
    level: int = logging.DEBUG,
) -> Iterator[logging.Logger]:
    """Attach a task-run-specific file handler for the current task context."""
    _install_task_record_factory()
    resolved_task_id = str(task_id or uuid.uuid4().hex)
    log_file = get_task_log_file(
        task_name,
        resolved_task_id,
        celery=celery,
        log_base_dir=log_base_dir,
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)

    project_root = PROJECT_ROOT
    formatter = RelativePathFormatter(LOG_FORMAT, LOG_DATE_FORMAT, relative_to=project_root)
    handler = FileHandler(
        log_file,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(_TaskLogFilter(resolved_task_id))
    handler._finance_task_handler = True  # type: ignore[attr-defined]
    handler._finance_task_name = task_name  # type: ignore[attr-defined]
    handler._finance_task_id = resolved_task_id  # type: ignore[attr-defined]

    root_logger = logging.getLogger()
    task_logger_name = "tasks.celery" if celery else "tasks.scheduled"
    task_logger = logging.getLogger(f"{task_logger_name}.{_sanitize_log_file_stem(task_name)}")

    task_id_token = _TASK_ID_CONTEXT.set(resolved_task_id)
    task_name_token = _TASK_NAME_CONTEXT.set(task_name)
    with _TASK_HANDLER_LOCK:
        root_logger.addHandler(handler)
    task_logger.info(
        "任务日志开始: task_name=%s task_id=%s log_file=%s",
        task_name,
        resolved_task_id,
        log_file,
    )
    try:
        yield task_logger
    except Exception:
        task_logger.exception("任务执行异常: task_name=%s task_id=%s", task_name, resolved_task_id)
        raise
    finally:
        task_logger.info("任务日志结束: task_name=%s task_id=%s", task_name, resolved_task_id)
        with _TASK_HANDLER_LOCK:
            root_logger.removeHandler(handler)
        handler.close()
        _TASK_NAME_CONTEXT.reset(task_name_token)
        _TASK_ID_CONTEXT.reset(task_id_token)


def _truncate_for_log(value: Any, limit: int = 2000) -> Any:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def _redact_mapping(data: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if data is None:
        return None
    redacted: Dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if any(token in key_text.lower() for token in ("token", "secret", "password", "key", "authorization")):
            redacted[key_text] = "***"
        else:
            redacted[key_text] = _truncate_for_log(value, 500)
    return redacted


def _extract_response_details(exc: Exception) -> Dict[str, Any]:
    details: Dict[str, Any] = {}
    response = getattr(exc, "response", None)
    request = getattr(response, "request", None) if response is not None else getattr(exc, "request", None)

    status_code = getattr(response, "status_code", None) if response is not None else getattr(exc, "code", None)
    if status_code is not None:
        details["status_code"] = status_code

    url = getattr(request, "url", None)
    if url is None and response is not None:
        url = getattr(response, "url", None)
    if url is None:
        url = getattr(exc, "url", None) or getattr(exc, "filename", None)
    if url:
        details["url"] = _truncate_for_log(url, 1000)

    method = getattr(request, "method", None)
    if method:
        details["method"] = method

    elapsed = getattr(response, "elapsed", None) if response is not None else None
    if elapsed is not None:
        try:
            details["response_elapsed_seconds"] = round(float(elapsed.total_seconds()), 3)
        except Exception:
            details["response_elapsed"] = str(elapsed)

    if response is not None:
        text = getattr(response, "text", None)
        if text:
            details["response_text"] = _truncate_for_log(text)
        else:
            content = getattr(response, "content", None)
            if content:
                details["response_body"] = _truncate_for_log(content)

    return details


def log_external_call_exception(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
    exc: Exception,
    symbol: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
    elapsed: Optional[float] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """Log rich diagnostics for external API/SDK failures."""
    details: Dict[str, Any] = {
        "provider": provider,
        "operation": operation,
        "exception_class": exc.__class__.__name__,
        "exception_repr": repr(exc),
        "exception_args": tuple(_truncate_for_log(arg, 500) for arg in getattr(exc, "args", ())),
    }
    if symbol:
        details["symbol"] = symbol
    if params:
        details["params"] = _redact_mapping(params)
    if elapsed is not None:
        details["elapsed_seconds"] = round(float(elapsed), 3)
    if exc.__cause__ is not None:
        details["cause_class"] = exc.__cause__.__class__.__name__
        details["cause_repr"] = repr(exc.__cause__)
    if exc.__context__ is not None and exc.__context__ is not exc.__cause__:
        details["context_class"] = exc.__context__.__class__.__name__
        details["context_repr"] = repr(exc.__context__)
    if extra:
        details["extra"] = _redact_mapping(extra)
    details.update(_extract_response_details(exc))

    logger.exception("外部接口调用异常: %s", details)
