# -*- coding: utf-8 -*-
"""Search module component (split from search_service.py)."""

import logging
from typing import Any, Dict

import requests
from newspaper import Article, Config
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# Transient network errors (retryable)
_SEARCH_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_SEARCH_TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _post_with_retry(url: str, *, headers: Dict[str, str], json: Dict[str, Any], timeout: int) -> requests.Response:
    """POST with retry on transient SSL/network errors."""
    return requests.post(url, headers=headers, json=json, timeout=timeout)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_SEARCH_TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _get_with_retry(
    url: str, *, headers: Dict[str, str], params: Dict[str, Any], timeout: int
) -> requests.Response:
    """GET with retry on transient SSL/network errors."""
    return requests.get(url, headers=headers, params=params, timeout=timeout)


def fetch_url_content(url: str, timeout: int = 5) -> str:
    """
    获取 URL 网页正文内容 (使用 newspaper3k)
    """
    try:
        # 配置 newspaper3k
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = timeout
        config.fetch_images = False  # 不下载图片
        config.memoize_articles = False # 不缓存

        article = Article(url, config=config, language='zh') # 默认中文，但也支持其他
        article.download()
        article.parse()

        # 获取正文
        text = article.text.strip()

        # 简单的后处理，去除空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        return text[:1500]  # 限制返回长度（比 bs4 稍微多一点，因为 newspaper 解析更干净）
    except Exception as e:
        logger.debug(f"Fetch content failed for {url}: {e}")

    return ""
