# -*- coding: utf-8 -*-
"""
===================================
Finance Analysis - 通知层
===================================

职责：
1. 汇总分析结果生成日报
2. 支持 Markdown 格式输出
3. 多渠道推送（自动识别）：
   - Telegram Bot
   - ntfy
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum

from finance_analysis.notification.config import get_notification_config
from finance_analysis.reporting.config import get_report_config
from finance_analysis.reporting.types import ReportType
from finance_analysis.notification.routing import (
    get_notification_route_config,
    split_notification_route_channels,
)
from finance_analysis.notification.noise_control import (
    NotificationNoiseDecision,
    evaluate_notification_noise,
    record_notification_noise,
    release_notification_noise,
)
from finance_analysis.reporting.localization import (
    get_localized_stock_name,
    get_report_labels,
    get_signal_level,
    localize_chip_health,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from finance_analysis.notification.messages import BotMessage
from finance_analysis.analysis.context_normalizer import normalize_model_used
from finance_analysis.notification.senders import (
    NtfySender,
    TelegramSender,
    resolve_ntfy_endpoint,
)
from finance_analysis.reporting.markdown_renderer import ReportRenderingMixin

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from finance_analysis.analysis.stock_report_analyzer import AnalysisResult


@dataclass
class NotificationResult:
    """Persistence establishes the message; push fields describe optional side effects only."""

    notification_id: Optional[int] = None
    push_attempted: bool = False
    push_sent: bool = False


class NotificationChannel(Enum):
    """通知渠道类型"""
    TELEGRAM = "telegram"  # Telegram
    NTFY = "ntfy"          # ntfy


class ChannelDetector:
    """
    渠道检测器 - 简化版
    
    根据配置直接判断渠道类型（不再需要 URL 解析）
    """
    
    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """获取渠道中文名称"""
        names = {
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.NTFY: "ntfy",
        }
        return names.get(channel, "未知渠道")


class NotificationService(
    ReportRenderingMixin,
    NtfySender,
    TelegramSender,
):
    """
    通知服务
    
    职责：
    1. 生成 Markdown 格式的分析日报
    2. 向所有已配置的渠道推送消息（多渠道并发）
    3. 在外部推送之前独立持久化消息
    
    支持的渠道：
    - Telegram Bot
    - ntfy
    
    注意：所有已配置的渠道都会收到推送
    """
    
    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        初始化通知服务

        检测所有已配置的渠道，推送时会向所有渠道发送
        """
        config = get_notification_config()
        report_config = get_report_config()
        self._config = config
        self._source_message = source_message
        self.last_notification_id: Optional[int] = None

        # Markdown 转图片（Issue #289）
        self._markdown_to_image_channels = set(
            getattr(report_config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            report_config, 'markdown_to_image_max_chars', 15000
        )

        # 仅分析结果摘要（Issue #262）：true 时只推送汇总，不含个股详情
        self._report_summary_only = getattr(report_config, 'report_summary_only', False)
        self._history_compare_cache: Dict[Tuple[int, Tuple[Tuple[str, str], ...]], Dict[str, List[Dict[str, Any]]]] = {}

        NtfySender.__init__(self, config)
        TelegramSender.__init__(self, config)

        self._available_channels = self._detect_all_channels()

        if not self._available_channels:
            logger.info("未配置有效的通知渠道，将不发送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            logger.info(f"已配置 {len(channel_names)} 个通知渠道：{', '.join(channel_names)}")

    def _normalize_report_type(self, report_type: Any) -> ReportType:
        """Normalize string/enum input into ReportType."""
        if isinstance(report_type, ReportType):
            return report_type
        return ReportType.from_str(report_type)

    def _get_report_language(self, payload: Optional[Any] = None) -> str:
        """Resolve report language from result payload or global config."""
        if isinstance(payload, list):
            for item in payload:
                language = getattr(item, "report_language", None)
                if language:
                    return normalize_report_language(language)
        elif payload is not None:
            language = getattr(payload, "report_language", None)
            if language:
                return normalize_report_language(language)

        return normalize_report_language(get_report_config().report_language)

    def _get_labels(self, payload: Optional[Any] = None) -> Dict[str, str]:
        return get_report_labels(self._get_report_language(payload))

    def _get_display_name(self, result: AnalysisResult, language: Optional[str] = None) -> str:
        report_language = normalize_report_language(language or self._get_report_language(result))
        return self._escape_md(
            get_localized_stock_name(result.name, result.code, report_language)
        )

    def _get_history_compare_context(self, results: List[AnalysisResult]) -> Dict[str, Any]:
        """Fetch and cache history comparison data for markdown rendering."""
        config = get_report_config()
        history_compare_n = getattr(config, 'report_history_compare_n', 0)
        if history_compare_n <= 0 or not results:
            return {"history_by_code": {}}

        cache_key = (
            history_compare_n,
            tuple(sorted((r.code, getattr(r, 'query_id', '') or '') for r in results)),
        )
        if cache_key in self._history_compare_cache:
            return {"history_by_code": self._history_compare_cache[cache_key]}

        try:
            from finance_analysis.analysis.history.comparison import get_signal_changes_batch

            exclude_ids = {
                r.code: r.query_id
                for r in results
                if getattr(r, 'query_id', None)
            }
            codes = list(dict.fromkeys(r.code for r in results))
            history_by_code = get_signal_changes_batch(
                codes,
                limit=history_compare_n,
                exclude_query_ids=exclude_ids,
            )
        except Exception as e:
            logger.debug("History comparison skipped: %s", e)
            history_by_code = {}

        self._history_compare_cache[cache_key] = history_by_code
        return {"history_by_code": history_by_code}

    def generate_aggregate_report(
        self,
        results: List[AnalysisResult],
        report_type: Any,
        report_date: Optional[str] = None,
    ) -> str:
        """Generate the aggregate report content used by merge/save/push paths."""
        normalized_type = self._normalize_report_type(report_type)
        if normalized_type == ReportType.BRIEF:
            return self.generate_brief_report(results, report_date=report_date)
        return self.generate_dashboard_report(results, report_date=report_date)

    def _collect_models_used(self, results: List[AnalysisResult]) -> List[str]:
        models: List[str] = []
        for result in results:
            model = normalize_model_used(getattr(result, "model_used", None))
            if model:
                models.append(model)
        return list(dict.fromkeys(models))
    
    @staticmethod
    def detect_configured_channels(config: object) -> List[NotificationChannel]:
        """
        Detect statically configured notification channels from Config.

        This intentionally mirrors sender availability without instantiating
        sender objects, so diagnostics and runtime use the same channel truth.
        Runtime-only context channels are handled by instance methods.
        """
        channels = []

        if (
            getattr(config, "telegram_bot_token", None)
            and getattr(config, "telegram_chat_id", None)
        ):
            channels.append(NotificationChannel.TELEGRAM)

        ntfy_server_url, ntfy_topic = resolve_ntfy_endpoint(getattr(config, "ntfy_url", None))
        if ntfy_server_url and ntfy_topic:
            channels.append(NotificationChannel.NTFY)

        return channels

    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        检测所有已配置的渠道

        Returns:
            已配置的渠道列表
        """
        return self.detect_configured_channels(self._config)

    def is_available(self) -> bool:
        """检查通知服务是否可用（至少有一个渠道）"""
        return len(self._available_channels) > 0
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """获取所有已配置的渠道"""
        return self._available_channels

    def get_channels_for_route(
        self,
        route_type: Optional[str],
        channels: Optional[List[NotificationChannel]] = None,
    ) -> List[NotificationChannel]:
        """Return channels allowed for a route type.

        ``route_type=None`` keeps the legacy behavior and returns all supplied
        static channels. Empty route config also keeps all supplied channels.
        Non-empty route config that matches no enabled channel returns an empty
        list.
        """
        target_channels = list(channels if channels is not None else self._available_channels)
        if route_type is None:
            return target_channels

        route_config = get_notification_route_config(route_type)
        if route_config is None:
            logger.warning("未知通知路由类型 %s，沿用全部已配置渠道", route_type)
            return target_channels

        configured_route_channels = getattr(self._config, route_config["config_attr"], []) or []
        if not configured_route_channels:
            return target_channels

        valid_channels, invalid_channels = split_notification_route_channels(configured_route_channels)
        if invalid_channels:
            logger.warning(
                "%s 包含未知通知渠道，将忽略: %s",
                route_config["env_key"],
                ", ".join(invalid_channels),
            )

        allowed = set(valid_channels)
        return [channel for channel in target_channels if channel.value in allowed]
    
    def get_channel_names(self) -> str:
        """获取所有已配置渠道的名称"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        return ', '.join(names)

    def evaluate_noise_control(
        self,
        content: str,
        *,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
    ) -> NotificationNoiseDecision:
        """Evaluate static-channel notification noise controls."""
        return evaluate_notification_noise(
            self._config,
            content=content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )

    @staticmethod
    def record_noise_control(decision: NotificationNoiseDecision) -> None:
        """Record static-channel notification noise state after a successful send."""
        record_notification_noise(decision)

    @staticmethod
    def release_noise_control(decision: NotificationNoiseDecision) -> None:
        """Release static-channel in-flight noise reservation after send failure."""
        release_notification_noise(decision)

    def _should_use_image_for_channel(
        self, channel: NotificationChannel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        """
        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        return True

    def persist(
        self, content: str, *, uid: Optional[int] = None, title: Optional[str] = None,
        route_type: Optional[str] = None, severity: Optional[str] = None,
    ) -> Optional[int]:
        """Record a business message independently of external delivery; fail open."""
        try:
            from finance_analysis.database.repositories.notification import NotificationRepository
            from finance_analysis.notification.noise_control import normalize_notification_severity

            heading = next((line.strip().strip("#* ") for line in content.splitlines() if line.strip()), "系统消息")
            return NotificationRepository().create(
                uid=uid, title=(title or heading)[:300], content=content,
                route_type=route_type or "report",
                severity=normalize_notification_severity(route_type, severity),
            )
        except Exception:
            logger.exception("Notification persistence failed")
            return None

    def send(
        self,
        content: str,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
        *,
        uid: Optional[int] = None,
        title: Optional[str] = None,
        push: bool = True,
        push_content: Optional[str] = None,
    ) -> NotificationResult:
        """Persist the full message, then attempt optional delivery without changing its outcome.

        Business callers must use notification_id, never push_sent, to mark a
        message handled. Noise control and image rendering use the actual push body.
        """
        notification_id = self.persist(content, uid=uid, title=title, route_type=route_type, severity=severity)
        self.last_notification_id = notification_id
        result = NotificationResult(notification_id=notification_id)
        if push:
            try:
                self._push_message(
                    result,
                    content if push_content is None else push_content,
                    route_type=route_type,
                    severity=severity,
                    dedup_key=dedup_key,
                    cooldown_key=cooldown_key,
                )
            except Exception:
                logger.exception("External notification delivery failed")
        return result

    def _push_message(
        self,
        result: NotificationResult,
        content: str,
        *,
        route_type: Optional[str],
        severity: Optional[str],
        dedup_key: Optional[str],
        cooldown_key: Optional[str],
    ) -> None:
        if not self._available_channels:
            logger.info("未配置外部通知渠道，跳过推送")
            return
        target_channels = self.get_channels_for_route(route_type)
        if not target_channels:
            logger.info("通知路由 %s 未命中外部渠道，跳过推送", route_type)
            return
        noise_decision = self.evaluate_noise_control(
            content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )
        if not noise_decision.should_send:
            logger.info(noise_decision.message)
            return
        try:
            image_bytes = None
            if any(
                ch.value in self._markdown_to_image_channels and ch != NotificationChannel.NTFY
                for ch in target_channels
            ):
                try:
                    from finance_analysis.reporting.md2img import markdown_to_image

                    image_bytes = markdown_to_image(content, max_chars=self._markdown_to_image_max_chars)
                except Exception:
                    logger.exception("Markdown image conversion failed; falling back to text")
            for channel in target_channels:
                try:
                    use_image = self._should_use_image_for_channel(channel, image_bytes)
                    result.push_attempted = True
                    if channel == NotificationChannel.TELEGRAM:
                        push_sent = (
                            self._send_telegram_photo(image_bytes) if use_image else self.send_to_telegram(content)
                        )
                    else:
                        push_sent = self.send_to_ntfy(content)
                    result.push_sent = bool(push_sent) or result.push_sent
                    if not push_sent:
                        logger.warning("%s 外部推送失败", channel.value)
                except Exception:
                    logger.exception("%s 外部推送失败", channel.value)
        finally:
            if result.push_sent:
                self.record_noise_control(noise_decision)
            else:
                self.release_noise_control(noise_decision)


class NotificationBuilder:
    """
    通知消息构建器
    
    提供便捷的消息构建方法
    """
    
    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        构建简单的提醒消息
        
        Args:
            title: 标题
            content: 内容
            alert_type: 类型（info, warning, error, success）
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")
        
        return f"{emoji} **{title}**\n\n{content}"
    
    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        构建股票摘要（简短版）
        
        适用于快速通知
        """
        report_language = normalize_report_language(
            next((getattr(result, "report_language", None) for result in results if getattr(result, "report_language", None)), None)
        )
        labels = get_report_labels(report_language)
        lines = [f"📊 **{labels['summary_heading']}**", ""]
        
        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            _, emoji, _ = get_signal_level(r.operation_advice, r.sentiment_score, report_language)
            name = get_localized_stock_name(r.name, r.code, report_language)
            lines.append(
                f"{emoji} {name}({r.code}): {localize_operation_advice(r.operation_advice, report_language)} | "
                f"{labels['score_label']} {r.sentiment_score}"
            )
        
        return "\n".join(lines)


# 便捷函数
def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> NotificationResult:
    """
    发送每日报告的快捷方式
    
    自动识别渠道并推送
    """
    service = get_notification_service()
    
    # 生成报告
    report = service.generate_daily_report(results)
    
    # 推送到配置的渠道（自动识别）
    return service.send(report)
