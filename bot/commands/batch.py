# -*- coding: utf-8 -*-
"""
===================================
批量分析命令
===================================

批量分析自选股列表中的所有股票。
"""

import logging
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class BatchCommand(BotCommand):
    """
    批量分析命令
    
    批量分析配置中的自选股列表，生成汇总报告。
    
    用法：
        /batch      - 分析所有自选股
        /batch 3    - 只分析前3只
    """
    
    @property
    def name(self) -> str:
        return "batch"
    
    @property
    def aliases(self) -> List[str]:
        return ["b", "批量", "全部"]
    
    @property
    def description(self) -> str:
        return "批量分析自选股"
    
    @property
    def usage(self) -> str:
        return "/batch [数量]"
    
    @property
    def admin_only(self) -> bool:
        """批量分析需要管理员权限（防止滥用）"""
        return False  # 可以根据需要设为 True
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行批量分析命令"""
        from src.repositories.watch_list_repo import get_watch_list_codes
        
        stock_list = get_watch_list_codes()
        
        if not stock_list:
            return BotResponse.error_response(
                "自选股列表为空，请先在 WebUI 自选股页面或通过 /api/v1/watch-list 接口添加"
            )
        
        # 解析数量参数
        limit = None
        if args:
            try:
                limit = int(args[0])
                if limit <= 0:
                    return BotResponse.error_response("数量必须大于0")
            except ValueError:
                return BotResponse.error_response(f"无效的数量: {args[0]}")
        
        # 限制分析数量
        if limit:
            stock_list = stock_list[:limit]
        
        logger.info(f"[BatchCommand] 开始批量分析 {len(stock_list)} 只股票")
        
        from src.tasks.bot_payload import bot_message_to_payload
        from src.tasks.queue import DuplicateTaskError, get_task_queue

        try:
            task = get_task_queue().submit_bot_batch_analysis(
                stock_codes=stock_list,
                bot_message=bot_message_to_payload(message),
            )
        except DuplicateTaskError as exc:
            return BotResponse.error_response(str(exc))
        except Exception as exc:
            logger.exception("[BatchCommand] 批量分析 Celery 任务提交失败: %s", exc)
            return BotResponse.error_response("批量分析任务提交失败，请稍后重试")

        return BotResponse.markdown_response(
            f"✅ **批量分析任务已启动**\n\n"
            f"• 任务 ID: `{task.task_id[:20]}...`\n"
            f"• 分析数量: {len(stock_list)} 只\n"
            f"• 股票列表: {', '.join(stock_list[:5])}"
            f"{'...' if len(stock_list) > 5 else ''}\n\n"
            f"分析完成后将自动推送汇总报告。"
        )
