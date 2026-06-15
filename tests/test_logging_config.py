# -*- coding: utf-8 -*-
"""Regression tests for application logging configuration."""

import logging
import types

import pytest

from src.logging_config import (
    LITELLM_LOGGERS,
    get_task_log_file,
    log_external_call_exception,
    setup_backend_logging,
    setup_logging,
    task_logging_context,
)


@pytest.fixture(autouse=True)
def restore_logging_state():
    root_logger = logging.getLogger()
    original_root_level = root_logger.level
    original_handlers = list(root_logger.handlers)
    original_litellm_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in LITELLM_LOGGERS
    }

    yield

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        if handler not in original_handlers:
            handler.close()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_root_level)

    for logger_name, level in original_litellm_levels.items():
        logging.getLogger(logger_name).setLevel(level)


def _read_debug_log(log_dir) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    debug_log = next(log_dir.glob("stock_analysis_debug_*.log"))
    return debug_log.read_text(encoding="utf-8")


@pytest.mark.parametrize("env_value", [None, "", "  "])
def test_litellm_debug_is_quiet_by_default_and_empty_env(tmp_path, monkeypatch, env_value):
    if env_value is None:
        monkeypatch.delenv("LITELLM_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("LITELLM_LOG_LEVEL", env_value)

    setup_logging(log_prefix="stock_analysis", log_dir=str(tmp_path), debug=False)

    for logger_name in LITELLM_LOGGERS:
        logging.getLogger(logger_name).debug("%s token debug should be filtered", logger_name)
    logging.getLogger("LiteLLM").warning("litellm warning should remain")
    logging.getLogger("src.sample").debug("project debug should remain")

    debug_log_text = _read_debug_log(tmp_path)

    for logger_name in LITELLM_LOGGERS:
        assert f"{logger_name} token debug should be filtered" not in debug_log_text
    assert "litellm warning should remain" in debug_log_text
    assert "project debug should remain" in debug_log_text


def test_litellm_log_level_debug_restores_litellm_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_LOG_LEVEL", "DEBUG")

    setup_logging(log_prefix="stock_analysis", log_dir=str(tmp_path), debug=False)

    for logger_name in LITELLM_LOGGERS:
        logging.getLogger(logger_name).debug("%s debug should remain", logger_name)

    debug_log_text = _read_debug_log(tmp_path)

    for logger_name in LITELLM_LOGGERS:
        assert f"{logger_name} debug should remain" in debug_log_text


def test_invalid_litellm_log_level_falls_back_to_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_LOG_LEVEL", "verbose")

    setup_logging(log_prefix="stock_analysis", log_dir=str(tmp_path), debug=False)

    logging.getLogger("LiteLLM").debug("invalid level debug should be filtered")
    logging.getLogger("LiteLLM").warning("invalid level warning should remain")

    debug_log_text = _read_debug_log(tmp_path)

    assert "invalid level debug should be filtered" not in debug_log_text
    assert "invalid level warning should remain" in debug_log_text
    assert "LITELLM_LOG_LEVEL" in debug_log_text
    assert "已回退为 WARNING" in debug_log_text


def test_setup_backend_logging_uses_service_subdirectory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))

    setup_backend_logging(service="server", log_prefix="web_server", debug=False)
    logging.getLogger("src.sample").info("server log routing works")
    for handler in logging.getLogger().handlers:
        handler.flush()

    server_log = next((tmp_path / "server").glob("web_server_*.log"))
    assert "server log routing works" in server_log.read_text(encoding="utf-8")


def test_task_logging_context_writes_task_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))

    setup_backend_logging(service="server", log_prefix="web_server", debug=False)
    with task_logging_context("analysis_daily"):
        logging.getLogger("src.sample").info("task log routing works")

    task_log = get_task_log_file("analysis_daily", log_base_dir=str(tmp_path))
    assert task_log.is_file()
    assert "task log routing works" in task_log.read_text(encoding="utf-8")


def test_celery_task_logging_context_uses_celery_task_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))

    setup_backend_logging(service="celery", log_prefix="celery", debug=False)
    with task_logging_context("demo.add", celery=True):
        logging.getLogger("src.sample").info("celery task log routing works")

    task_log = get_task_log_file("demo.add", celery=True, log_base_dir=str(tmp_path))
    assert task_log.is_file()
    assert "celery task log routing works" in task_log.read_text(encoding="utf-8")


def test_external_call_exception_logs_response_details(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    setup_backend_logging(service="server", log_prefix="web_server", debug=False)

    request = types.SimpleNamespace(method="GET", url="https://example.test/quote")
    response = types.SimpleNamespace(
        status_code=503,
        text="upstream unavailable",
        request=request,
        elapsed=types.SimpleNamespace(total_seconds=lambda: 1.25),
    )
    exc = RuntimeError("sdk failed")
    exc.response = response

    try:
        raise exc
    except RuntimeError as caught:
        log_external_call_exception(
            logging.getLogger("src.sample"),
            provider="example",
            operation="quote",
            exc=caught,
            symbol="AAPL",
            params={"token": "secret", "period": "1d"},
            elapsed=1.3,
        )

    for handler in logging.getLogger().handlers:
        handler.flush()
    debug_log = next((tmp_path / "server").glob("web_server_debug_*.log"))
    text = debug_log.read_text(encoding="utf-8")
    assert "status_code" in text
    assert "503" in text
    assert "upstream unavailable" in text
    assert "'token': '***'" in text
