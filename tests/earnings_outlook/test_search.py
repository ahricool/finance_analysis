"""Search requests, configuration and actual transport execution are distinct."""

import json
import shlex

from finance_analysis.llm import api, remote_cli
from finance_analysis.llm.config import LLMConfig
from finance_analysis.llm.client import LLMClient
from finance_analysis.llm.types import LLMRequest, LLMResult
from finance_analysis.llm.search import evidence


def test_codex_live_config_and_completed_search_events_only():
    config = LLMConfig(backend="cli", cli_engine="codex")
    args = shlex.split(remote_cli.build_command(config, 60, web_search=True))
    assert 'web_search="live"' in args
    events = [
        dict(type="item.completed", item=dict(type="web_search", id="s1", query="A.US 2026 Q2 earnings")),
        dict(type="item.completed", item=dict(type="agent_message", text='{"sources": []}')),
        dict(type="turn.completed", usage={}),
    ]
    result = remote_cli.parse_codex("\n".join(json.dumps(e) for e in events))
    assert result.search_evidence["status"] == "confirmed"
    result = remote_cli.parse_codex("\n".join(json.dumps(e) for e in events[1:]))
    assert result.search_evidence["status"] == "unverified"
    assert evidence(True, False)["status"] == "unavailable"


def test_api_annotations_not_model_claims_confirm_search(monkeypatch):
    import litellm

    response = {"choices": [{"message": {"content": '{"sources": [{"url": "https://example.com"}]}'}}]}
    called = []
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: (called.append(kwargs) or response))
    config = LLMConfig(model="gateway-model", api_key="test", api_search_mode="chat_completions")
    req = LLMRequest(prompt="A.US Q2 earnings", web_search=True, prefer_search=True)
    assert api.complete(config, req).search_evidence["status"] == "unverified"
    response["choices"][0]["message"]["annotations"] = [
        dict(type="url_citation", url_citation=dict(url="https://example.com", title="IR"))
    ]
    assert api.complete(config, req).search_evidence["status"] == "confirmed"
    assert called[-1]["num_retries"] == 0 and "web_search_options" in called[-1]
    config.api_search_mode = "unavailable"
    api.complete(config, req)
    assert "web_search_options" not in called[-1]


def test_earnings_prefers_supported_fallback_without_changing_other_callers(monkeypatch):
    config = LLMConfig(
        fallback_chain="agy,codex,api",
        model="x",
        api_key="test",
        cli_ssh_username="test",
        cli_ssh_password="test",
        max_retries=0,
    )
    client = LLMClient(config)
    monkeypatch.setattr(client, "_record", lambda *a, **kw: None)
    calls = []

    def cli(request, deadline, config):
        calls.append(config.cli_engine)
        return LLMResult(text="ok", backend="cli", search_evidence={"status": "confirmed"})

    monkeypatch.setattr(client, "_complete_cli", cli)
    client.complete_text(LLMRequest(prompt="ordinary"))
    assert calls == ["agy"]
    calls.clear()
    client.complete_text(LLMRequest(prompt="earnings", web_search=True, prefer_search=True))
    assert calls == ["codex"]
