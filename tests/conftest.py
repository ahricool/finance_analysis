"""Keep application request-retry backoffs deterministic and offline in tests."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def external_retry_waits(monkeypatch):
    from finance_analysis.core import retry

    sync_wait, async_wait = Mock(), AsyncMock()
    monkeypatch.setattr(retry, "sleep", sync_wait)
    monkeypatch.setattr(retry, "async_sleep", async_wait)
    return sync_wait, async_wait
