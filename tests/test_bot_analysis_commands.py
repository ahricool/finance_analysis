# -*- coding: utf-8 -*-
"""Tests for bot analysis commands submitting Celery-backed tasks."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot.commands.analyze import AnalyzeCommand
from bot.commands.batch import BatchCommand
from bot.models import BotMessage, ChatType
from src.tasks.queue import DuplicateTaskError


def _make_message(content: str) -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content=content,
        raw_content=content,
        mentioned=False,
        timestamp=datetime.now(),
    )


def test_analyze_command_submits_bot_stock_analysis_task() -> None:
    task_queue = MagicMock()
    task_queue.submit_bot_analysis.return_value = SimpleNamespace(task_id="analysis-task-1234567890")

    with patch("src.tasks.queue.get_task_queue", return_value=task_queue):
        response = AnalyzeCommand().execute(_make_message("/analyze 600519"), ["600519", "full"])

    assert "分析任务已提交" in response.text
    task_queue.submit_bot_analysis.assert_called_once()
    kwargs = task_queue.submit_bot_analysis.call_args.kwargs
    assert kwargs["stock_code"] == "600519"
    assert kwargs["report_type"] == "full"
    assert kwargs["bot_message"]["message_id"] == "m1"


def test_analyze_command_duplicate_returns_error_response() -> None:
    task_queue = MagicMock()
    task_queue.submit_bot_analysis.side_effect = DuplicateTaskError("600519.SH", "task-1")

    with patch("src.tasks.queue.get_task_queue", return_value=task_queue):
        response = AnalyzeCommand().execute(_make_message("/analyze 600519"), ["600519"])

    assert not response.markdown
    assert "正在分析中" in response.text


def test_batch_command_submits_bot_batch_analysis_task() -> None:
    task_queue = MagicMock()
    task_queue.submit_bot_batch_analysis.return_value = SimpleNamespace(task_id="batch-task-1234567890")

    with patch("src.repositories.watch_list_repo.get_watch_list_codes", return_value=["600519", "000001"]), \
         patch("src.tasks.queue.get_task_queue", return_value=task_queue):
        response = BatchCommand().execute(_make_message("/batch"), ["1"])

    assert "批量分析任务已启动" in response.text
    task_queue.submit_bot_batch_analysis.assert_called_once()
    kwargs = task_queue.submit_bot_batch_analysis.call_args.kwargs
    assert kwargs["stock_codes"] == ["600519"]
    assert kwargs["bot_message"]["message_id"] == "m1"
