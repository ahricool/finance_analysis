"""Backend selection, a single retry budget, attempt audit and usage statistics."""

import json
import logging
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
            raise LLMError("Selected LLM backend is not configured")
        if request.timeout is not None and request.timeout <= 0:
            raise ValueError("Request timeout must be positive")
        request_id = uuid.uuid4().hex
        # Timeout is the total call budget, including the optional retry.
        deadline = time.monotonic() + (request.timeout or self.config.timeout)
        last_error = "LLM call failed"
        for attempt in range(1, self.config.max_retries + 2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if attempt > 1:
                if remaining <= RETRY_DELAYS[attempt - 2]:
                    break
                wait_before_retry(attempt - 2)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
            started = time.monotonic()
            result = None
            error = None
            try:
                if self.config.backend == "api":
                    result = api.complete(self.config, replace(request, timeout=remaining))
                else:
                    result = self._complete_cli(request, deadline)
                if validator:
                    validator(result.text)
            except Exception as exc:
                # Never stringify a vendor exception: it may include keys, headers or host diagnostics.
                error = f"{self.config.backend} call failed ({type(exc).__name__})"
                last_error = error
            duration_ms = round((time.monotonic() - started) * 1000)
            if result:
                result.duration_ms = duration_ms
            self._record(request, result, request_id, attempt, duration_ms, error)
            if error is None:
                return result
        raise LLMError(last_error) from None

    def _complete_cli(self, request: LLMRequest, deadline: float) -> LLMResult:
        """Serialize one attempt on a pinned PostgreSQL session, within its budget."""
        from sqlalchemy import text

        from finance_analysis.database import DatabaseManager

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
                        raise TimeoutError("CLI advisory lock deadline exceeded")
                    try:
                        acquired = bool(connection.execute(
                            text("SELECT pg_try_advisory_lock(:key)"), params,
                        ).scalar_one())
                    except BaseException:
                        # An interrupted query may have acquired the lock on the
                        # server. Never return that uncertain session to the pool.
                        connection.invalidate()
                        raise
                    if not acquired:
                        time.sleep(min(CLI_LOCK_POLL_SECONDS, max(0, deadline - time.monotonic())))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("CLI advisory lock deadline exceeded")
                return remote_cli.complete(self.config, replace(request, timeout=remaining))
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

    def _record(self, request, result, request_id, attempt, duration_ms, error):
        config = self.config
        now = utc_now()
        usage = result.usage if result else {}
        model = result.model if result else (config.model if config.backend == "api" else config.cli_model or None)
        engine = config.cli_engine if config.backend == "cli" else None
        status = "failed" if error else "success"
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
