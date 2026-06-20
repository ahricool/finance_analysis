# -*- coding: utf-8 -*-
"""
===================================
状态命令
===================================

显示系统运行状态和配置信息。
"""

import platform
import sys
from datetime import datetime
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse


class StatusCommand(BotCommand):
    """
    状态命令
    
    显示系统运行状态，包括：
    - 服务状态
    - 配置信息
    - 可用功能
    """
    
    @property
    def name(self) -> str:
        return "status"
    
    @property
    def aliases(self) -> List[str]:
        return ["s", "状态", "info"]
    
    @property
    def description(self) -> str:
        return "显示系统状态"
    
    @property
    def usage(self) -> str:
        return "/status"
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行状态命令"""
        # 收集状态信息
        status_info = self._collect_status()
        
        # 格式化输出
        text = self._format_status(status_info, message.platform)
        
        return BotResponse.markdown_response(text)
    
    def _collect_status(self) -> dict:
        """收集系统状态信息"""
        from src.agent.config import get_agent_config
        from src.llm import is_llm_configured
        from src.llm.config import get_llm_config
        from src.notification_config import get_notification_config
        from src.repositories.watch_list_repo import get_watch_list_codes
        from src.search.config import get_search_config

        try:
            watch_codes = get_watch_list_codes()
        except Exception:  # 容错：状态命令不应因为 DB 不可用而崩溃
            watch_codes = []

        status = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "stock_count": len(watch_codes),
            "stock_list": watch_codes[:5],  # 只显示前5个
        }
        
        llm_config = get_llm_config()
        agent_config = get_agent_config()
        search_config = get_search_config()
        notification_config = get_notification_config()

        llm_model = (llm_config.model or "").strip()
        agent_model = (agent_config.agent_litellm_model or "").strip()
        status["ai_primary_model"] = llm_model
        status["ai_agent_model"] = agent_model or ("继承主模型" if llm_model else "")
        status["ai_channels"] = []
        status["ai_yaml"] = False
        status["ai_legacy_keys"] = {}
        status["ai_available"] = is_llm_configured(llm_config)
        
        # 搜索服务状态
        status["search_bocha"] = len(search_config.bocha_api_keys) > 0
        status["search_tavily"] = len(search_config.tavily_api_keys) > 0
        status["search_brave"] = len(search_config.brave_api_keys) > 0
        status["search_serpapi"] = len(search_config.serpapi_keys) > 0
        status["search_minimax"] = len(search_config.minimax_api_keys) > 0
        status["search_searxng"] = search_config.has_searxng_enabled()
        
        # 通知渠道状态
        status["notify_telegram"] = bool(notification_config.telegram_bot_token and notification_config.telegram_chat_id)
        status["notify_email"] = bool(notification_config.email_sender and notification_config.email_password)
        status["notify_ntfy"] = bool(notification_config.ntfy_url)
        status["notify_custom"] = bool(notification_config.custom_webhook_urls)
        status["notify_astrbot"] = bool(notification_config.astrbot_url)
        
        return status
    
    def _format_status(self, status: dict, platform: str) -> str:
        """格式化状态信息"""
        # 状态图标
        def icon(enabled: bool) -> str:
            return "✅" if enabled else "❌"
        
        lines = [
            "📊 **股票分析助手 - 系统状态**",
            "",
            f"🕐 时间: {status['timestamp']}",
            f"🐍 Python: {status['python_version']}",
            f"💻 平台: {status['platform']}",
            "",
            "---",
            "",
            "**📈 自选股配置**",
            f"• 股票数量: {status['stock_count']} 只",
        ]
        
        if status['stock_list']:
            stocks_preview = ", ".join(status['stock_list'])
            if status['stock_count'] > 5:
                stocks_preview += f" ... 等 {status['stock_count']} 只"
            lines.append(f"• 股票列表: {stocks_preview}")
        
        lines.extend([
            "",
            "**🤖 AI 分析服务**",
            f"• 主模型: {status['ai_primary_model'] or '未配置'}",
            f"• Agent 模型: {status['ai_agent_model'] or '未配置'}",
            f"• LLM 渠道: {', '.join(status['ai_channels']) if status['ai_channels'] else '未配置'}",
            f"• LiteLLM YAML: {icon(status['ai_yaml'])}",
            "• Legacy Key: "
            + ", ".join(
                f"{name}{icon(enabled)}"
                for name, enabled in status["ai_legacy_keys"].items()
            ),
            "",
            "**🔍 搜索服务**",
            f"• Bocha: {icon(status['search_bocha'])}",
            f"• Tavily: {icon(status['search_tavily'])}",
            f"• Brave: {icon(status['search_brave'])}",
            f"• SerpAPI: {icon(status['search_serpapi'])}",
            f"• MiniMax: {icon(status['search_minimax'])}",
            f"• SearXNG: {icon(status['search_searxng'])}",
            "",
            "**📢 通知渠道**",
            f"• Telegram: {icon(status['notify_telegram'])}",
            f"• 邮件: {icon(status['notify_email'])}",
            f"• ntfy: {icon(status['notify_ntfy'])}",
            f"• 自定义 Webhook: {icon(status['notify_custom'])}",
            f"• AstrBot: {icon(status['notify_astrbot'])}",
        ])
        
        # AI 服务总体状态
        if status["ai_available"]:
            lines.extend([
                "",
                "---",
                "✅ **系统就绪，可以开始分析！**",
            ])
        else:
            lines.extend([
                "",
                "---",
                "⚠️ **AI 服务未配置，分析功能不可用**",
                "请配置 LITELLM_MODEL、LLM_CHANNELS、LITELLM_CONFIG 或任一 provider API Key",
            ])
        
        return "\n".join(lines)
