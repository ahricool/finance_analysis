# -*- coding: utf-8 -*-
"""Tests for bot MarketCommand Celery submission and trading-day filtering."""

import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from finance_analysis.interfaces.bot.commands.market import MarketCommand
from finance_analysis.interfaces.bot.models import BotMessage, ChatType
from finance_analysis.tasks.queue import DuplicateTaskError


def _make_message() -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content="/market",
        raw_content="/market",
        mentioned=False,
        timestamp=datetime.now(),
    )


class MarketCommandRegionFilterTestCase(unittest.TestCase):
    def _patch_dependencies(
        self,
        *,
        market_review_region: str,
        open_markets: set,
        trading_day_check_enabled: bool = True,
    ):
        config = SimpleNamespace(
            market_review_region=market_review_region,
            trading_day_check_enabled=trading_day_check_enabled,
        )
        config_module = MagicMock()
        config_module.get_config.return_value = config
        trading_calendar_module = MagicMock()
        trading_calendar_module.get_open_markets_today.return_value = open_markets

        from finance_analysis.market_review.trading_calendar import compute_effective_region

        trading_calendar_module.compute_effective_region.side_effect = compute_effective_region

        patcher = patch.dict(
            sys.modules,
            {
                "finance_analysis.config": config_module,
                "finance_analysis.market_review.trading_calendar": trading_calendar_module,
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return config

    def test_both_with_cn_us_open_submits_override_region_cn_us(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "us"},
        )
        task_queue = MagicMock()
        task_queue.submit_market_review.return_value = SimpleNamespace(task_id="market-task-1234567890")

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            response = MarketCommand().execute(message, [])

        self.assertIn("任务已启动", response.text)
        task_queue.submit_market_review.assert_called_once()
        kwargs = task_queue.submit_market_review.call_args.kwargs
        self.assertTrue(kwargs["send_notification"])
        self.assertEqual(kwargs["override_region"], "cn,us")
        self.assertEqual(kwargs["bot_message"]["message_id"], "m1")

    def test_both_with_cn_hk_open_submits_override_region_cn_hk(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "hk"},
        )
        task_queue = MagicMock()
        task_queue.submit_market_review.return_value = SimpleNamespace(task_id="market-task-1234567890")

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            MarketCommand().execute(message, [])

        self.assertEqual(task_queue.submit_market_review.call_args.kwargs["override_region"], "cn,hk")

    def test_all_relevant_markets_closed_skips_review(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="cn",
            open_markets=set(),
        )
        task_queue = MagicMock()

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            response = MarketCommand().execute(message, [])

        self.assertIn("休市", response.text)
        task_queue.submit_market_review.assert_not_called()

    def test_trading_day_check_disabled_does_not_pass_override(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn"},
            trading_day_check_enabled=False,
        )
        task_queue = MagicMock()
        task_queue.submit_market_review.return_value = SimpleNamespace(task_id="market-task-1234567890")

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            MarketCommand().execute(message, [])

        self.assertIsNone(task_queue.submit_market_review.call_args.kwargs["override_region"])

    def test_duplicate_market_review_submission_returns_busy_message(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="cn",
            open_markets={"cn"},
        )
        task_queue = MagicMock()
        task_queue.submit_market_review.side_effect = DuplicateTaskError("market_review", "task-1")

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            response = MarketCommand().execute(message, [])

        self.assertIn("正在执行中", response.text)

    def test_submit_failure_returns_error_response(self) -> None:
        message = _make_message()
        self._patch_dependencies(
            market_review_region="cn",
            open_markets={"cn"},
        )
        task_queue = MagicMock()
        task_queue.submit_market_review.side_effect = RuntimeError("broker unavailable")

        with patch("finance_analysis.tasks.queue.get_task_queue", return_value=task_queue):
            response = MarketCommand().execute(message, [])

        self.assertFalse(response.markdown)
        self.assertIn("大盘复盘启动失败", response.text)


if __name__ == "__main__":
    unittest.main()
