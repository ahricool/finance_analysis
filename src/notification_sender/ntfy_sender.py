# -*- coding: utf-8 -*-
"""ntfy notification sender."""

from __future__ import annotations

import logging
from datetime import datetime
from email.header import Header
from typing import Optional, Tuple
from urllib.parse import quote, unquote, urlparse, urlunparse

import requests

from src.config import Config


logger = logging.getLogger(__name__)

# ntfy JSON publish rejects payloads above this size with HTTP 500.
NTFY_INLINE_MESSAGE_LIMIT = 4096


def resolve_ntfy_endpoint(ntfy_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split NTFY_URL into server root and topic from the final path segment."""
    raw_url = (ntfy_url or "").strip().rstrip("/")
    if not raw_url:
        return None, None

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, None

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        return None, None

    topic = unquote(path_segments[-1]).strip()
    if not topic:
        return None, None

    root_path = "/".join(path_segments[:-1])
    server_url = urlunparse(
        parsed._replace(
            path=f"/{root_path}" if root_path else "",
            params="",
            query="",
            fragment="",
        )
    ).rstrip("/")

    return server_url, topic


def build_ntfy_publish_url(server_url: str, topic: str) -> str:
    """Build the topic publish URL for Markdown/text notifications."""
    return f"{server_url}/{quote(topic, safe='')}"


def encode_ntfy_header(value: str) -> str:
    """Encode header values for HTTP while preserving UTF-8 titles."""
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        return Header(value, charset="utf-8").encode()


class NtfySender:
    """Send Markdown text notifications through the ntfy topic publish API."""

    def __init__(self, config: Config):
        self._ntfy_url = getattr(config, "ntfy_url", None)
        self._ntfy_token = getattr(config, "ntfy_token", None)
        self._webhook_verify_ssl = getattr(config, "webhook_verify_ssl", True)

    def _is_ntfy_configured(self) -> bool:
        return bool(self._ntfy_url)

    def _resolve_ntfy_endpoint(self) -> Tuple[Optional[str], Optional[str]]:
        return resolve_ntfy_endpoint(self._ntfy_url)

    def send_to_ntfy(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Publish a Markdown notification to ntfy.

        Uses POST to the topic URL so large reports are stored as attachments
        instead of failing the JSON publish API's 4 KB inline limit.
        """
        if not self._is_ntfy_configured():
            logger.warning("ntfy URL 未配置，跳过推送")
            return False

        server_url, topic = self._resolve_ntfy_endpoint()
        if not server_url or not topic:
            logger.error("NTFY_URL 必须是包含 topic path 的完整 endpoint，例如 https://ntfy.sh/my-topic")
            return False

        date_str = datetime.now().strftime("%Y-%m-%d")
        if title is None:
            title = f"📈 Finance Analysis 报告 - {date_str}"

        headers = {
            "User-Agent": "finance-analysis",
            "Title": encode_ntfy_header(title),
            "Markdown": "yes",
        }
        token = (self._ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        body = content.encode("utf-8")
        if len(body) > NTFY_INLINE_MESSAGE_LIMIT:
            headers["Filename"] = f"finance-analysis-report-{date_str}.md"

        publish_url = build_ntfy_publish_url(server_url, topic)

        try:
            response = requests.post(
                publish_url,
                data=body,
                headers=headers,
                timeout=timeout_seconds or 10,
                verify=self._webhook_verify_ssl,
            )
            if 200 <= response.status_code < 300:
                logger.info("ntfy 消息发送成功")
                return True

            response_preview = (response.text or "").strip().replace("\n", " ")[:200]
            logger.error(
                "ntfy 请求失败: HTTP %s%s",
                response.status_code,
                f" ({response_preview})" if response_preview else "",
            )
            return False
        except requests.exceptions.Timeout:
            logger.error("发送 ntfy 消息失败: 请求超时")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("发送 ntfy 消息失败: 网络请求异常")
            logger.debug("ntfy 请求异常类型: %s", type(exc).__name__)
            return False
        except Exception as exc:
            logger.error("发送 ntfy 消息失败: 未知异常")
            logger.debug("ntfy 未知异常类型: %s", type(exc).__name__)
            return False
