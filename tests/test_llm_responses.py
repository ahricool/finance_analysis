"""OpenAI Responses search routing and transport-backed research evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_analysis.llm import api
from finance_analysis.llm.config import LLMConfig, get_llm_config
from finance_analysis.llm.failures import ProviderFailure
from finance_analysis.llm.search import supported
from finance_analysis.llm.types import LLMRequest


@pytest.fixture
def response():
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "web_search_call", "id": "s1", "status": "completed", "action": {"type": "search"}},
            {"type": "message", "content": [
                {"type": "output_text", "text": '{"facts": []}', "annotations": [
                    {"type": "url_citation", "url": "https://example.com/ir", "title": "IR"},
                ]},
            ]},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
    }


@pytest.fixture
def config():
    return LLMConfig(
        model="openai/gpt-6.1-sol", api_key="test", api_effort="medium", api_search_mode="responses"
    )


def test_responses_search_request_and_evidence(config, response, monkeypatch):
    import litellm

    call = Mock(return_value=response)
    monkeypatch.setattr(litellm, "responses", call)
    monkeypatch.setattr(litellm, "completion", Mock(side_effect=AssertionError("Wrong endpoint")))
    request = LLMRequest("Verify the filing", system_prompt="Use primary sources", web_search=True, prefer_search=True)
    result = api.complete(config, request)
    kwargs = call.call_args.kwargs
    assert kwargs["input"] == request.prompt and kwargs["instructions"] == request.system_prompt
    assert kwargs["api_base"] == "https://api.openai.com/v1"
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["tools"] == [{"type": "web_search", "search_context_size": "medium"}]
    assert kwargs["num_retries"] == 0 and kwargs["store"] is False
    assert not {"temperature", "max_tokens", "max_completion_tokens", "max_output_tokens"} & kwargs.keys()
    assert result.text == '{"facts": []}'
    assert result.usage == {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130}
    assert result.search_evidence["status"] == "confirmed"
    assert result.search_evidence["citations"] == [{"url": "https://example.com/ir", "title": "IR"}]
    assert result.search_evidence["tool_events"][0]["id"] == "s1"
    assert "api_ms" in request.diagnostics


@pytest.mark.parametrize("search_status,expected", [("completed", "confirmed"), ("in_progress", "unverified")])
def test_only_completed_tool_events_confirm_search(config, response, monkeypatch, search_status, expected):
    import litellm

    response["output"][1]["status"] = search_status
    response["output"][2]["content"][0]["annotations"] = []
    monkeypatch.setattr(litellm, "responses", Mock(return_value=response))
    result = api.complete(config, LLMRequest("Verify", web_search=True))
    assert result.search_evidence["status"] == expected


def test_model_source_claims_do_not_confirm_search(config, response, monkeypatch):
    import litellm

    response["output"] = [response["output"][2]]
    part = response["output"][0]["content"][0]
    part["annotations"] = []
    part["text"] = '{"sources": ["https://example.com"]}'
    monkeypatch.setattr(litellm, "responses", Mock(return_value=response))
    assert api.complete(config, LLMRequest("Verify", web_search=True)).search_evidence["status"] == "unverified"


def test_responses_sdk_objects_and_direct_annotations(config, response, monkeypatch):
    import litellm

    response["output"] = [response["output"][2]]
    response["output"][0]["content"][0]["annotations"].append(
        {"type": "url_citation", "url": "file:///secret", "title": "ignore"}
    )

    def objects(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{k: objects(v) for k, v in value.items()})
        return [objects(v) for v in value] if isinstance(value, list) else value

    monkeypatch.setattr(litellm, "responses", Mock(return_value=objects(response)))
    result = api.complete(config, LLMRequest("Verify", web_search=True))
    assert result.search_evidence["status"] == "confirmed"
    assert len(result.search_evidence["citations"]) == 1


@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress"])
def test_partial_responses_rejected_even_when_text_exists(config, response, monkeypatch, status):
    import litellm

    response["status"] = status
    monkeypatch.setattr(litellm, "responses", Mock(return_value=response))
    with pytest.raises(ProviderFailure, match="invalid_output"):
        api.complete(config, LLMRequest("Verify", web_search=True))


@pytest.mark.parametrize("search,mode", [(False, "responses"), (True, "unavailable")])
def test_ordinary_or_disabled_search_stays_on_chat(config, monkeypatch, search, mode):
    import litellm

    config.api_search_mode = mode
    call = Mock(return_value={"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(litellm, "completion", call)
    monkeypatch.setattr(litellm, "responses", Mock(side_effect=AssertionError("Unexpected search")))
    api.complete(config, LLMRequest("OK", web_search=search))
    assert "web_search_options" not in call.call_args.kwargs


def test_responses_capability_requires_openai_and_env_can_enable(monkeypatch):
    monkeypatch.setenv("LLM_API_SEARCH_MODE", "responses")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6.1-sol")
    get_llm_config.cache_clear()
    try:
        config = get_llm_config()
        assert supported(config)
        config.model = "other/model"
        assert not supported(config)
    finally:
        get_llm_config.cache_clear()
