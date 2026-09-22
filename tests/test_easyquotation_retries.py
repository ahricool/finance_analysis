"""Offline coverage for per-batch Tencent transport retries."""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout, SSLError

from finance_analysis.integrations.market_data.providers import easyquotation as module


@pytest.fixture
def transport(monkeypatch):
    import easyquotation

    get = Mock()
    client = SimpleNamespace(_session=SimpleNamespace(get=get))
    monkeypatch.setattr(easyquotation, "use", lambda _: client)
    wait = Mock()
    monkeypatch.setattr(module, "sleep", wait)
    provider = module.EasyQuotationProvider()
    return provider, client, get, wait


@pytest.mark.parametrize("error", [ConnectionError, ReadTimeout])
def test_failed_batch_recovers_without_repeating_successful_batch(transport, error):
    provider, client, get, wait = transport
    response = object()
    get.side_effect = [response, error("offline"), error("offline"), response]
    provider._client()
    assert client._session.get("http://qt.gtimg.cn/q=sh510300") is response
    assert client._session.get("http://qt.gtimg.cn/q=bj830896") is response
    assert get.call_args_list == [
        call("http://qt.gtimg.cn/q=sh510300", timeout=30),
        *[call("http://qt.gtimg.cn/q=bj830896", timeout=30)] * 3,
    ]
    assert wait.call_args_list == [call(1.0), call(2.0)]


def test_exhaustion_propagates_last_error_and_does_not_stack_wrappers(transport):
    provider, client, get, wait = transport
    error = ConnectionError("network unreachable")
    get.side_effect = error
    provider._client()
    wrapped = client._session.get
    provider._client()
    assert client._session.get is wrapped
    with pytest.raises(ConnectionError) as caught:
        client._session.get("http://qt.gtimg.cn/q=sh510300", timeout=4)
    assert caught.value is error
    assert get.call_args_list == [call("http://qt.gtimg.cn/q=sh510300", timeout=4)] * 3
    assert wait.call_args_list == [call(1.0), call(2.0)]


@pytest.mark.parametrize("error", [SSLError, HTTPError, ValueError])
def test_non_transient_errors_are_not_retried(transport, error):
    provider, client, get, wait = transport
    get.side_effect = error("invalid")
    provider._client()
    with pytest.raises(error):
        client._session.get("http://qt.gtimg.cn/q=sh510300")
    assert get.call_count == 1
    wait.assert_not_called()

