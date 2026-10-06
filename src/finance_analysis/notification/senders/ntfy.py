# -*- coding: utf-8 -*-
"""ntfy notification sender."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse, urlunparse

import requests


from finance_analysis.core.retry import retry_call, transient_response

logger = logging.getLogger(__name__)

# ntfy defaults: 4096-byte message, twice that for the serialized JSON envelope.
# https://github.com/binwiederhier/ntfy/blob/main/server/server.go (transformBodyJSON)
MESSAGE_LIMIT_BYTES = 4096
JSON_LIMIT_BYTES = 2 * MESSAGE_LIMIT_BYTES


def _publish_bodies(topic: str, title: str, content: str) -> list[bytes]:
    def encode(message: str) -> bytes:
        return json.dumps({"topic": topic, "title": title, "message": message, "markdown": True},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def fits(message: str) -> bool:
        return len(message.encode("utf-8")) <= MESSAGE_LIMIT_BYTES and len(encode(message)) <= JSON_LIMIT_BYTES

    if fits(content):
        return [encode(content)]
    # The number of parts cannot exceed the number of characters. Reserve the
    # largest possible numbering prefix, including it in both byte limits.
    digits = len(str(len(content)))
    reserved_prefix = f"[{'9' * digits}/{'9' * digits}]\n"
    if not fits(reserved_prefix):
        raise ValueError("ntfy metadata leaves no room for multipart messages")
    chunks = []
    offset = 0
    while offset < len(content):
        low, high = 0, min(len(content) - offset, MESSAGE_LIMIT_BYTES)
        while low < high:
            middle = (low + high + 1) // 2
            if fits(reserved_prefix + content[offset:offset + middle]):
                low = middle
            else:
                high = middle - 1
        if not low:
            raise ValueError("ntfy metadata leaves no room for a message character")
        # Prefer whole lines when possible, retaining the newline and all text.
        newline = content.rfind("\n", offset, offset + low)
        if newline >= offset + low // 2:
            low = newline + 1 - offset
        chunks.append(content[offset:offset + low])
        offset += low
    return [encode(f"[{index}/{len(chunks)}]\n" + chunk) for index, chunk in enumerate(chunks, 1)]



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


class NtfySender:
    """Send Markdown text notifications through the ntfy JSON publish API."""

    def __init__(self, config: object):
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
        """Publish a notification to ntfy using a JSON body with UTF-8 text."""
        if not self._is_ntfy_configured():
            logger.warning("ntfy URL 未配置，跳过推送")
            return False

        server_url, topic = self._resolve_ntfy_endpoint()
        if not server_url or not topic:
            logger.error("NTFY_URL 必须是包含 topic path 的完整 endpoint，例如 https://ntfy.sh/my-topic")
            return False

        if title is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            title = f"📈 Finance Analysis 报告 - {date_str}"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "finance-analysis",
        }
        token = (self._ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            bodies = _publish_bodies(topic, title, content)
            for index, body in enumerate(bodies, 1):
                response = retry_call(lambda: requests.post(
                    server_url,
                    data=body,
                    headers=headers,
                    timeout=timeout_seconds or 10,
                    verify=self._webhook_verify_ssl,
                ), retry_result=transient_response)
                if not 200 <= response.status_code < 300:
                    logger.error("ntfy 请求失败: HTTP %s, part=%s/%s", response.status_code, index, len(bodies))
                    logger.debug("ntfy 响应内容: %s", response.text)
                    return False
            logger.info("ntfy 消息发送成功: parts=%s", len(bodies))
            return True
        except requests.exceptions.Timeout:
            logger.error("发送 ntfy 消息失败: 请求超时")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("发送 ntfy 消息失败: 网络请求异常")
            logger.debug("ntfy 请求异常类型: %s", type(exc).__name__)
            return False
        except Exception as exc:
            logger.exception("发送 ntfy 消息失败: 未知异常")
            logger.debug("ntfy 未知异常类型: %s", type(exc).__name__)
            return False
