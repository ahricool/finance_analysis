"""Unified retry contracts and integration-boundary recovery, without network I/O."""

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, call

import httpx
import pandas as pd
import pytest
import requests

from finance_analysis.core import retry
from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.integrations.crypto.binance import BinanceClient
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider


@pytest.mark.parametrize("failure", [requests.ConnectionError, requests.Timeout, httpx.ReadTimeout, TimeoutError])
def test_transport_exhaustion_is_four_calls_and_three_backoffs(failure, external_retry_waits):
    error = failure("secret must not be logged")
    operation = Mock(side_effect=error)
    with pytest.raises(failure) as caught:
        retry.retry_call(operation)
    assert caught.value is error
    assert operation.call_count == 4
    assert external_retry_waits[0].call_args_list == [call(2), call(4), call(8)]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 429, 500, 502, 503, 504])
def test_http_status_policy(status, external_retry_waits):
    responses = []

    def operation():
        response = httpx.Response(status)
        responses.append(response)
        return response

    result = retry.retry_call(operation, retry_result=retry.transient_response)
    transient = status in {408, 429} or status >= 500
    assert len(responses) == (4 if transient else 1)
    assert result is responses[-1]
    assert external_retry_waits[0].call_count == (3 if transient else 0)


def test_success_stops_and_no_request_url_or_secret_in_logs(external_retry_waits, caplog):
    operation = Mock(side_effect=[requests.Timeout("https://secret/token"), "ok"])
    assert retry.retry_call(operation) == "ok"
    assert external_retry_waits[0].call_args_list == [call(2)]
    assert "secret" not in caplog.text


def test_exhausted_budget_prevents_wait_and_second_request(external_retry_waits):
    operation = Mock(side_effect=requests.Timeout())
    before_wait = Mock(side_effect=TimeoutError("budget exhausted"))
    with pytest.raises(TimeoutError, match="budget exhausted"):
        retry.retry_call(operation, before_wait=before_wait)
    assert operation.call_count == 1
    external_retry_waits[0].assert_not_called()


@pytest.mark.parametrize("failure", [ValueError, requests.exceptions.SSLError])
def test_permanent_failures_are_not_retried(failure, external_retry_waits):
    operation = Mock(side_effect=failure("invalid"))
    with pytest.raises(failure):
        retry.retry_call(operation)
    assert operation.call_count == 1
    external_retry_waits[0].assert_not_called()


def test_fuyao_transport_and_server_errors_share_one_budget(external_retry_waits):
    outcomes = iter([httpx.ConnectError("offline"), 503, 429, 200])
    requests_seen = []

    def handler(request):
        requests_seen.append(request)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, json={"code": 0, "data": {"ok": True}})

    provider = FuyaoProvider(api_key="test", transport=httpx.MockTransport(handler))
    assert provider._get("/test") == {"ok": True}
    assert len(requests_seen) == 4
    assert external_retry_waits[0].call_args_list == [call(2), call(4), call(8)]


def test_yahoo_preview_retries_only_missing_symbols(monkeypatch, external_retry_waits):
    provider = YFinanceProvider()
    calls = []

    def download(symbols, **kwargs):
        calls.append(list(symbols))
        available = ["AAPL"] if len(calls) == 1 else symbols
        frames = {symbol: pd.DataFrame(
            {"Open": [100], "High": [102], "Low": [99], "Close": [101], "Volume": [5]},
            index=pd.DatetimeIndex(["2026-09-22T14:00:00Z"], name="Datetime"),
        ) for symbol in available}
        return pd.concat(frames, axis=1)

    monkeypatch.setattr(provider, "_download", download)
    result = provider.fetch_intraday_preview_daily_bars(["AAPL.US", "MSFT.US"], date(2026, 9, 22))
    assert calls == [["AAPL", "MSFT"], ["MSFT"]]
    assert set(result.data) == {"AAPL.US", "MSFT.US"}
    assert result.failed_symbols == {}
    assert external_retry_waits[0].call_args_list == [call(2)]


def test_binance_server_error_recovery(external_retry_waits):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(503 if len(seen) < 4 else 200, json={"serverTime": 1})

    async def run():
        async with httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(handler)) as http:
            return await BinanceClient(CryptoConfig(), http).server_time()

    assert asyncio.run(run()).timestamp() == .001
    assert len(seen) == 4
    assert external_retry_waits[1].call_args_list == [call(2), call(4), call(8)]


def test_async_cancellation_is_not_retried(external_retry_waits):
    from unittest.mock import AsyncMock

    operation = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retry.retry_async(operation))
    assert operation.call_count == 1
    external_retry_waits[1].assert_not_called()


@pytest.mark.parametrize("kind", ["plain", "photo", "ntfy"])
def test_notification_paths_share_retry_policy(monkeypatch, external_retry_waits, kind):
    from finance_analysis.notification.senders.telegram import TelegramSender
    from finance_analysis.notification.senders.ntfy import NtfySender

    response = Mock(status_code=200)
    response.json.return_value = {"ok": True}
    post = Mock(side_effect=[requests.Timeout(), response])
    monkeypatch.setattr(requests, "post", post)
    sender = TelegramSender(SimpleNamespace(telegram_bot_token="test", telegram_chat_id="test"))
    if kind == "plain":
        assert sender._send_plain_text_fallback("https://test.invalid", {"chat_id": "test"}, "text")
    elif kind == "photo":
        assert sender._send_telegram_photo(b"image")
    else:
        sender = NtfySender(SimpleNamespace(ntfy_url="https://test.invalid/topic"))
        assert sender.send_to_ntfy("test")
    assert post.call_count == 2
    assert external_retry_waits[0].call_args_list == [call(2)]


def test_tickflow_disables_sdk_retries(monkeypatch):
    import tickflow
    from finance_analysis.integrations.market_data.providers.tickflow import TickFlowFreeProvider

    factory = Mock()
    monkeypatch.setattr(tickflow.TickFlow, "free", factory)
    assert TickFlowFreeProvider()._get_client() is factory.return_value
    factory.assert_called_once_with(timeout=30.0, max_retries=0)


def test_llm_budget_includes_backoff(monkeypatch, tmp_path, external_retry_waits):
    from finance_analysis.llm import LLMClient, LLMError, LLMRequest, api
    from finance_analysis.llm.config import LLMConfig

    client = LLMClient(LLMConfig(model="test", api_key="test", timeout=1, log_dir=tmp_path))
    monkeypatch.setattr(client, "_record", lambda *args: None)
    operation = Mock(side_effect=TimeoutError())
    monkeypatch.setattr(api, "complete", operation)
    with pytest.raises(LLMError):
        client.complete_text(LLMRequest("test"))
    assert operation.call_count == 1
    external_retry_waits[0].assert_not_called()


def test_longbridge_news_retries_before_returning_empty(monkeypatch, external_retry_waits):
    from finance_analysis.integrations.market_data.providers.longbridge.news import LongbridgeNewsFetcher

    provider = object.__new__(LongbridgeNewsFetcher)
    context = SimpleNamespace(news=Mock(side_effect=[TimeoutError(), []]))
    monkeypatch.setattr(provider, "is_available", lambda: True)
    monkeypatch.setattr(provider, "_get_ctx", lambda: context)
    assert provider.fetch_news("AAPL.US") == []
    assert context.news.call_count == 2
    assert external_retry_waits[0].call_args_list == [call(2)]
