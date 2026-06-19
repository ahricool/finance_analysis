# -*- coding: utf-8 -*-
"""
===================================
大盘复盘命令
===================================

执行大盘复盘分析，生成市场概览报告。
"""

import logging
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class MarketCommand(BotCommand):
    """
    大盘复盘命令

    执行大盘复盘分析，包括：
    - 主要指数表现
    - 板块热点
    - 市场情绪
    - 后市展望

    用法：
        /market - 执行大盘复盘
    """

    @property
    def name(self) -> str:
        return "market"

    @property
    def aliases(self) -> List[str]:
        return ["m", "大盘", "复盘", "行情"]

    @property
    def description(self) -> str:
        return "大盘复盘分析"

    @property
    def usage(self) -> str:
        return "/market"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行大盘复盘命令"""
        config = self._get_config()
        try:
            override_region = self._compute_market_review_override_region(config)
            if override_region == "":
                return BotResponse.markdown_response("🎯 大盘复盘\n\n今日相关市场休市，已跳过大盘复盘。")

            from src.tasks.bot_payload import bot_message_to_payload
            from src.tasks.queue import DuplicateTaskError, get_task_queue

            task = get_task_queue().submit_market_review(
                send_notification=True,
                override_region=override_region,
                bot_message=bot_message_to_payload(message),
            )
        except DuplicateTaskError:
            return BotResponse.markdown_response("⚠️ 大盘复盘正在执行中，请稍后再试。")
        except Exception as exc:
            logger.exception(
                "[MarketCommand] 大盘复盘 Celery 任务提交失败: %s",
                exc,
            )
            return BotResponse.error_response(
                "大盘复盘启动失败，请稍后重试"
            )

        return BotResponse.markdown_response(
            "✅ **大盘复盘任务已启动**\n\n"
            f"• 任务 ID: `{task.task_id[:20]}...`\n\n"
            "正在分析：\n"
            "• 主要指数表现\n"
            "• 板块热点分析\n"
            "• 市场情绪判断\n"
            "• 后市展望\n\n"
            "分析完成后将自动推送结果。"
        )

    def _get_config(self):
        from src.config import get_config
        return get_config()

    def _compute_market_review_override_region(self, config) -> Optional[str]:
        if not getattr(config, "trading_day_check_enabled", True):
            return None

        try:
            from src.core.trading_calendar import (
                get_open_markets_today,
                compute_effective_region,
            )

            open_markets = get_open_markets_today()
            return compute_effective_region(
                getattr(config, "market_review_region", "cn") or "cn",
                open_markets,
            )
        except Exception as exc:
            logger.warning("交易日过滤失败，按配置继续执行大盘复盘: %s", exc)
            return None
