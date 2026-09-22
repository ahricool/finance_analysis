"""Bounded retries at external request boundaries, with no payload/URL logging."""

from __future__ import annotations

import logging
import ssl
from asyncio import sleep as async_sleep
from collections.abc import Awaitable, Callable
from time import sleep
from typing import TypeVar

import httpx
import requests

T = TypeVar("T")
RETRY_DELAYS = (2, 4, 8)
logger = logging.getLogger(__name__)


def transient_error(exc: Exception) -> bool:
    """Retry transport failures and temporary HTTP errors, not auth or bad data."""
    cause = exc
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, (ssl.SSLError, requests.exceptions.SSLError)):
            return False
        cause = cause.__cause__ or cause.__context__
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in {408, 429} or 500 <= status < 600
    if isinstance(
        exc, (ConnectionError, TimeoutError, requests.ConnectionError, requests.Timeout, httpx.TransportError),
    ):
        return True
    # SDKs can wrap native transport errors without retaining their Python type.
    module = type(exc).__module__
    if module.startswith(("longbridge", "longport", "tickflow", "curl_cffi", "yfinance")):
        reason = f"{type(exc).__name__} {exc}".lower()
        return any(word in reason for word in (
            "timeout", "timed out", "connection", "network", "rate limit", "too many requests",
            "temporarily unavailable", "resolve host",
        ))
    return False


def transient_response(response) -> bool:
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and (status in {408, 429} or 500 <= status < 600)


def wait_before_retry(attempt: int, *, before_wait: Callable[[float], None] | None = None) -> None:
    delay = RETRY_DELAYS[attempt]
    if before_wait is not None:
        before_wait(delay)
    logger.warning("external_request retry=%s delay_seconds=%s", attempt + 1, delay)
    sleep(delay)


def retry_call(
    operation: Callable[[], T], *, retryable: Callable[[Exception], bool] = transient_error,
    retry_result: Callable[[T], bool] | None = None,
    before_wait: Callable[[float], None] | None = None, max_retries: int = 3,
) -> T:
    """At most four attempts. Callers retain their own final error/result semantics."""
    limit = min(max(0, max_retries), len(RETRY_DELAYS))
    for attempt in range(limit + 1):
        try:
            result = operation()
        except Exception as exc:
            if attempt == limit or not retryable(exc):
                raise
        else:
            if attempt == limit or retry_result is None or not retry_result(result):
                return result
            if callable(getattr(result, "close", None)):
                result.close()
        wait_before_retry(attempt, before_wait=before_wait)
    raise AssertionError("unreachable")


async def retry_async(operation: Callable[[], Awaitable[T]]) -> T:
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt == len(RETRY_DELAYS) or not transient_error(exc):
                raise
        delay = RETRY_DELAYS[attempt]
        logger.warning("external_request retry=%s delay_seconds=%s", attempt + 1, delay)
        await async_sleep(delay)
    raise AssertionError("unreachable")
