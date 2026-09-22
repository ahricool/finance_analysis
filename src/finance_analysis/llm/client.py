"""Ordered provider fallback with bounded retries, deadlines and safe attempt audit."""

import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import replace
from typing import Callable

from finance_analysis.core.retry import RETRY_DELAYS, wait_before_retry
from finance_analysis.core.time import utc_now

from . import api, remote_cli
from .config import LLMConfig, get_llm_config
from .failures import ProviderFailure, classify_exception
from .types import LLMRequest, LLMResult

logger = logging.getLogger(__name__)

# One stable bigint key for every CLI engine, host, user and worker. PostgreSQL's
# single-bigint key space is separate from the two-integer task mutex keys.
CLI_ADVISORY_LOCK_KEY = 0x46415F4C4C4D434C  # ASCII FA_LLMCL
CLI_LOCK_POLL_SECONDS = 1.0


class LLMError(RuntimeError):
    """A safe failure summary; transport exceptions may contain credentials."""


class LLMClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or get_llm_config()

    def is_available(self) -> bool:
        return self.config.is_available()

    def complete_text(self, request: LLMRequest, validator: Callable[[str], None] | None = None) -> LLMResult:
        if not self.is_available():
            raise LLMError("No configured LLM provider is available")
        total = self.config.timeout if request.timeout is None else request.timeout
        if not math.isfinite(total) or total <= 0:
            raise ValueError("Request timeout must be positive and finite")
        if not isinstance(request.prompt, str) or not request.prompt.strip():
            raise ValueError("Request prompt must be nonempty text")
        request_id = uuid.uuid4().hex
        deadline = time.monotonic() + total
        providers = self.config.providers()
        failures = []
        attempt = 0
        for index, config in enumerate(providers):
            name = config.cli_engine if config.backend == "cli" else "api"
            if not config.is_available():
                failures.append(f"{name}:not_configured")
                self._record(request, None, request_id, attempt, 0, "not_configured", config=config, skipped=True)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failures.append(f"{name}:deadline_exceeded")
                break
            later = sum(c.is_available() for c in providers[index + 1 :])
            # Reserve a first attempt for each remaining configured provider.
            reserve = later * min(self.config.attempt_timeout, max(0, remaining) / (later + 1))
            stage_deadline = deadline - reserve
            failure = None
            for provider_attempt in range(config.max_retries + 1):
                if provider_attempt:
                    delay = max(RETRY_DELAYS[provider_attempt - 1], failure.retry_after or 0)
                    if stage_deadline - time.monotonic() <= delay:
                        break
                    wait_before_retry(provider_attempt - 1)
                    extra = delay - RETRY_DELAYS[provider_attempt - 1]
                    if extra > 0:
                        time.sleep(extra)
                remaining = stage_deadline - time.monotonic()
                if remaining <= 0:
                    break
                attempt_deadline = stage_deadline
                if self.config.fallback_chain:
                    attempt_deadline = min(stage_deadline, time.monotonic() + self.config.attempt_timeout)
                attempt += 1
                started = time.monotonic()
                result = None
                failure = None
                try:
                    if config.backend == "api":
                        result = api.complete(config, replace(request, timeout=attempt_deadline - time.monotonic()))
                    else:
                        result = self._complete_cli(request, attempt_deadline, config)
                    if time.monotonic() >= attempt_deadline:
                        raise ProviderFailure("timeout")
                    if not result.text.strip():
                        raise ProviderFailure("empty_response", retryable=True)
                    if validator:
                        try:
                            validator(result.text)
                        except ValueError:
                            raise ProviderFailure("invalid_output", retryable=True) from None
                except Exception as exc:
                    failure = classify_exception(exc)
                duration_ms = round((time.monotonic() - started) * 1000)
                if result:
                    result.duration_ms = duration_ms
                self._record(
                    request, result, request_id, attempt, duration_ms, failure.code if failure else None, config=config
                )
                if failure is None:
                    return result
                failures.append(f"{name}:{failure.code}")
                if failure.fatal:
                    raise LLMError("LLM failed: " + " → ".join(failures)) from None
                if not failure.retryable:
                    break
        raise LLMError("LLM failed: " + " → ".join(failures or ["deadline_exceeded"])) from None

    def _complete_cli(self, request: LLMRequest, deadline: float, config: LLMConfig | None = None) -> LLMResult:
        """Serialize one attempt on a pinned PostgreSQL session, within its budget."""
        config = config or self.config
        from sqlalchemy import text

        from finance_analysis.database import DatabaseManager

        try:
            with DatabaseManager.get_instance().connect() as connection:
                # No idle transaction while waiting or executing SSH. A session lock
                # survives autocommit and belongs to this checked-out connection.
                connection.execution_options(isolation_level="AUTOCOMMIT")
                acquired = False
                params = {"key": CLI_ADVISORY_LOCK_KEY}
                try:
                    while not acquired:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ProviderFailure("lock_wait_timeout", fatal=True)
                        try:
                            acquired = bool(
                                connection.execute(
                                    text("SELECT pg_try_advisory_lock(:key)"),
                                    params,
                                ).scalar_one()
                            )
                        except BaseException:
                            # An interrupted query may have acquired the lock on the
                            # server. Never return that uncertain session to the pool.
                            connection.invalidate()
                            raise
                        if not acquired:
                            time.sleep(min(CLI_LOCK_POLL_SECONDS, max(0, deadline - time.monotonic())))
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderFailure("lock_wait_timeout", fatal=True)
                    try:
                        return remote_cli.complete(config, replace(request, timeout=remaining))
                    except Exception as exc:
                        raise classify_exception(exc) from None
                finally:
                    if acquired:
                        try:
                            if not connection.execute(text("SELECT pg_advisory_unlock(:key)"), params).scalar_one():
                                raise RuntimeError("CLI advisory lock was lost")
                        except BaseException:
                            # close()/rollback alone would leave a session lock in
                            # the pool. Discard the physical connection on failure.
                            connection.invalidate()
                            raise
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure("lock_unavailable", fatal=True) from None

    def _record(self, request, result, request_id, attempt, duration_ms, error, *, config=None, skipped=False):
        config = config or self.config
        now = utc_now()
        usage = result.usage if result else {}
        model = result.model if result else (config.model if config.backend == "api" else config.cli_model or None)
        engine = config.cli_engine if config.backend == "cli" else None
        status = "skipped" if skipped else "failed" if error else "success"
        record = dict(
            timestamp=now.isoformat(),
            request_id=request_id,
            attempt=attempt,
            call_type=request.call_type,
            backend=config.backend,
            engine=engine,
            model=model,
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            response=result.text if result else None,
            usage=usage,
            duration_ms=duration_ms,
            status=status,
            error=error,
        )
        try:
            config.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

            def redact(value):
                if isinstance(value, str):
                    for secret in (config.api_key, config.cli_ssh_password):
                        if secret:
                            value = value.replace(secret, "[REDACTED]")
                    return re.sub(r"(?i)authorization\s*[:=]\s*[^\n]+", "[REDACTED]", value)
                if isinstance(value, dict):
                    return {key: redact(item) for key, item in value.items()}
                return value

            payload = json.dumps(redact(record), ensure_ascii=False)
            # File lock keeps JSONL records intact across Celery worker processes.
            import fcntl

            fd = os.open(
                config.log_dir / f"{now.date().isoformat()}.log",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                handle.write(payload + "\n")
        except Exception:
            logger.warning("LLM attempt audit could not be written")
        if skipped:
            return  # No paid/model attempt; preserve usage call counts.
        try:
            from finance_analysis.database import DatabaseManager

            DatabaseManager.get_instance().record_llm_usage(
                uid=request.uid,
                call_type=request.call_type,
                backend=config.backend,
                engine=engine,
                model=model,
                status=status,
                duration_ms=duration_ms,
                error=error,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
        except Exception:
            logger.warning("LLM usage statistics could not be saved")
