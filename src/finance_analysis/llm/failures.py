"""Safe, allowlisted failure categories; vendor text never escapes this boundary."""

import math


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, *, retryable=False, fatal=False, retry_after=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.fatal = fatal
        self.retry_after = retry_after


def classify_exception(exc: Exception) -> ProviderFailure:
    if isinstance(exc, ProviderFailure):
        return exc
    # Type/status classification only. Do not turn arbitrary application errors
    # into provider retries or include vendor messages in logs.
    import httpx
    import paramiko

    if isinstance(exc, paramiko.AuthenticationException):
        return ProviderFailure("authentication_failed")
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or type(exc).__name__ in {"Timeout", "APITimeoutError"}:
        return ProviderFailure("timeout")
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if status in {401, 403}:
        return ProviderFailure("authentication_failed")
    if status == 404:
        return ProviderFailure("model_unavailable")
    if status == 429:
        # LiteLLM retains provider error text; inspect it only in memory for
        # known hard quota phrases, never return or log it.
        message = str(exc).lower()
        if any(s in message for s in ("insufficient_quota", "individual quota reached", "exceeded your current quota")):
            return ProviderFailure("quota_exhausted")
        headers = getattr(response, "headers", {}) or {}
        try:
            delay = float(headers.get("retry-after", "nan"))
        except (TypeError, ValueError):
            delay = float("nan")
        return ProviderFailure(
            "rate_limited", retryable=True, retry_after=delay if math.isfinite(delay) and delay >= 0 else None
        )
    if isinstance(status, int):
        if status == 408 or 500 <= status < 600:
            return ProviderFailure("service_unavailable", retryable=True)
        return ProviderFailure("invalid_request", fatal=True)
    if isinstance(exc, (ConnectionError, OSError, httpx.TransportError, paramiko.SSHException)):
        return ProviderFailure("connection_failed", retryable=True)
    if type(exc).__name__ == "APIConnectionError":
        return ProviderFailure("connection_failed", retryable=True)
    return ProviderFailure("internal_error", fatal=True)
