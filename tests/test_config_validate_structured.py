# -*- coding: utf-8 -*-
"""Tests for Config.validate_structured() and backward-compatible validate().

Covers:
- ConfigIssue dataclass basics
- validate_structured() severity classifications
- LLM availability check honours unified LLM_MODEL / LLM_API_KEY config
- validate() backward-compat: still returns List[str] with the same messages
"""
import pytest
from dataclasses import fields
from unittest.mock import patch

from src.config import Config, ConfigIssue

_ALLOWED_CONFIG_FIELDS = {f.name for f in fields(Config)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> Config:
    """Build a minimal Config object with sensible defaults for testing.

    Any keyword argument overrides the corresponding dataclass field so tests
    only have to specify the fields that matter for their scenario.
    """
    defaults = dict(
        tushare_token=None,
        llm_model="gemini/gemini-2.0-flash",
        llm_base_url=None,
        llm_api_key="sk-test-key",
        llm_temperature=0.7,
        llm_fallback_models=[],
        bocha_api_keys=[],
        tavily_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        searxng_base_urls=[],
        searxng_public_instances_enabled=True,
        telegram_bot_token=None,
        telegram_chat_id=None,
        email_sender=None,
        email_password=None,
        pushover_user_key=None,
        pushover_api_token=None,
        pushplus_token=None,
        serverchan3_sendkey=None,
        custom_webhook_urls=["https://example.com/webhook"],
        discord_bot_token=None,
        discord_main_channel_id=None,
        discord_webhook_url=None,
        discord_interactions_public_key=None,
        database_url="postgresql+psycopg2://test:test@127.0.0.1:5432/test_db",
    )
    defaults.update(kwargs)
    filtered = {k: v for k, v in defaults.items() if k in _ALLOWED_CONFIG_FIELDS}
    return Config(**filtered)


def _severities(issues):
    return [i.severity for i in issues]


def _fields(issues):
    return [i.field for i in issues]


# ---------------------------------------------------------------------------
# ConfigIssue basics
# ---------------------------------------------------------------------------

class TestConfigIssue:
    def test_str_equals_message(self):
        issue = ConfigIssue(severity="error", message="something went wrong", field="FOO")
        assert str(issue) == "something went wrong"

    def test_severity_values(self):
        for sev in ("error", "warning", "info"):
            issue = ConfigIssue(severity=sev, message="test", field="F")
            assert issue.severity == sev

    def test_default_field(self):
        issue = ConfigIssue(severity="info", message="hello")
        assert issue.field == ""


# ---------------------------------------------------------------------------
# validate_structured() — happy path (all good)
# ---------------------------------------------------------------------------

class TestValidateStructuredHappyPath:
    def test_no_issues_when_fully_configured(self):
        cfg = _make_config()
        issues = cfg.validate_structured()
        # No errors or warnings; only possible info about tushare / search
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# validate_structured() — database
# ---------------------------------------------------------------------------

class TestValidateStructuredDatabase:
    def test_empty_database_url_is_error(self):
        cfg = _make_config(database_url="")
        issues = cfg.validate_structured()
        errors = [i for i in issues if i.severity == "error"]
        assert any(i.field == "DATABASE_URL" for i in errors)

    def test_non_postgresql_database_url_is_error(self):
        cfg = _make_config(database_url="mysql+pymysql://user:pass@localhost/db")
        issues = cfg.validate_structured()
        errors = [i for i in issues if i.severity == "error"]
        assert any(i.field == "DATABASE_URL" for i in errors)

    def test_get_db_url_raises_when_empty(self):
        cfg = _make_config(database_url="")
        with pytest.raises(ValueError, match="DATABASE_URL"):
            cfg.get_db_url()


# ---------------------------------------------------------------------------
# validate_structured() — watch_list (database)
# ---------------------------------------------------------------------------

class TestValidateStructuredWatchList:
    @patch("src.repositories.watch_list_repo.get_watch_list_codes", return_value=[])
    def test_empty_watch_list_emits_info(self, _mock_codes):
        cfg = _make_config()
        issues = cfg.validate_structured()
        info = next(i for i in issues if i.field == "watch_list")
        assert info.severity == "info"
        assert "自选股" in info.message

    @patch("src.repositories.watch_list_repo.get_watch_list_codes", return_value=["600519"])
    def test_configured_watch_list_has_no_watch_list_issue(self, _mock_codes):
        cfg = _make_config()
        issues = cfg.validate_structured()
        assert not any(i.field == "watch_list" for i in issues)

    @patch("src.repositories.watch_list_repo.get_watch_list_codes", side_effect=RuntimeError("db down"))
    def test_watch_list_db_unavailable_does_not_block_validation(self, _mock_codes):
        cfg = _make_config()
        issues = cfg.validate_structured()
        assert not any(i.field == "watch_list" for i in issues)

    def test_stock_email_groups_no_longer_validated_against_stock_list(self):
        """STOCK_GROUP_N 路由校验已移除；仅保留分组解析，不再与 .env 自选股比对。"""
        cfg = _make_config(
            stock_email_groups=[(["600519", "000001"], ["group@example.com"])],
        )
        issues = cfg.validate_structured()
        assert not any(i.field == "STOCK_GROUP_N" for i in issues)

# ---------------------------------------------------------------------------
# validate_structured() — LLM availability (three-tier check)
# ---------------------------------------------------------------------------

class TestValidateStructuredLLM:
    def test_no_llm_model_is_error(self):
        cfg = _make_config(llm_model="")
        issues = cfg.validate_structured()
        assert any(i.severity == "error" and i.field == "LLM_MODEL" for i in issues)

    def test_missing_api_key_is_error(self):
        cfg = _make_config(llm_api_key="")
        issues = cfg.validate_structured()
        assert any(i.severity == "error" and i.field == "LLM_API_KEY" for i in issues)

    def test_configured_llm_has_no_error(self):
        cfg = _make_config(
            llm_model="openai/gpt-5.5",
            llm_api_key="sk-test-key",
            llm_base_url="https://proxy.example/v1",
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and i.field.startswith("LLM_") for i in issues)

    def test_ollama_without_api_key_is_allowed(self):
        cfg = _make_config(
            llm_model="ollama/qwen3:8b",
            llm_api_key="",
            llm_base_url="http://localhost:11434",
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and i.field == "LLM_API_KEY" for i in issues)


# ---------------------------------------------------------------------------
# validate_structured() — notification & search
# ---------------------------------------------------------------------------

class TestValidateStructuredNotification:
    def test_no_notification_is_warning(self):
        cfg = _make_config(custom_webhook_urls=[])
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.severity == "warning"]
        assert any("通知渠道" in i.message for i in warn)

    def test_notification_configured_no_warning(self):
        cfg = _make_config(custom_webhook_urls=["https://example.com/wh"])
        issues = cfg.validate_structured()
        assert not any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_astrbot_url_counts_as_notification_channel(self):
        cfg = _make_config(
            custom_webhook_urls=[],
            astrbot_url="https://astrbot.example/webhook",
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_ntfy_url_without_topic_reports_error_and_does_not_count_as_channel(self):
        cfg = _make_config(custom_webhook_urls=[], ntfy_url="https://ntfy.sh")
        issues = cfg.validate_structured()

        assert any(i.severity == "error" and i.field == "NTFY_URL" for i in issues)
        assert any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_ntfy_encoded_blank_topic_reports_error_and_does_not_count_as_channel(self):
        cfg = _make_config(custom_webhook_urls=[], ntfy_url="https://ntfy.sh/%20")
        issues = cfg.validate_structured()

        assert any(i.severity == "error" and i.field == "NTFY_URL" for i in issues)
        assert any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_ntfy_topic_endpoint_counts_as_notification_channel(self):
        cfg = _make_config(custom_webhook_urls=[], ntfy_url="https://ntfy.sh/fa-topic")
        issues = cfg.validate_structured()

        assert not any(i.field == "NTFY_URL" for i in issues)
        assert not any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_invalid_notification_noise_config_reports_errors(self):
        cfg = _make_config(
            notification_quiet_hours="9:00-18:00",
            notification_timezone="Mars/Olympus",
            notification_min_severity="notice",
        )
        issues = cfg.validate_structured()
        errors = {(i.field, i.severity) for i in issues}

        assert ("NOTIFICATION_QUIET_HOURS", "error") in errors
        assert ("NOTIFICATION_TIMEZONE", "error") in errors
        assert ("NOTIFICATION_MIN_SEVERITY", "error") in errors

    def test_daily_digest_reserved_flag_warns_without_blocking(self):
        cfg = _make_config(notification_daily_digest_enabled=True)
        issues = cfg.validate_structured()

        assert any(
            issue.field == "NOTIFICATION_DAILY_DIGEST_ENABLED"
            and issue.severity == "warning"
            for issue in issues
        )

    def test_no_search_engine_is_info(self):
        cfg = _make_config(searxng_public_instances_enabled=False)
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert any("搜索引擎" in i.message for i in info)
        search_issue = next(i for i in info if "搜索引擎" in i.message)
        assert search_issue.field == "BOCHA_API_KEYS"

    def test_searxng_configured_no_search_info(self):
        """When searxng_base_urls is configured, no 'unconfigured search engine' info."""
        cfg = _make_config(searxng_base_urls=["https://searx.example.org"])
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert not any("搜索引擎" in i.message and "未配置" in i.message for i in info)

    def test_public_searxng_enabled_no_search_info(self):
        """Public SearXNG mode also counts as search capability."""
        cfg = _make_config(searxng_public_instances_enabled=True)
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert not any("搜索引擎" in i.message and "未配置" in i.message for i in info)


# ---------------------------------------------------------------------------
# Deprecated field migration hints
# ---------------------------------------------------------------------------

class TestDeprecatedFieldHints:
    def test_openai_vision_model_deprecation_when_env_set(self):
        """When OPENAI_VISION_MODEL is in env, validate_structured reports deprecation hint."""
        cfg = _make_config()
        with patch.dict("os.environ", {"OPENAI_VISION_MODEL": "openai/gpt-4o"}, clear=False):
            issues = cfg.validate_structured()
        deprec = [i for i in issues if i.field == "OPENAI_VISION_MODEL"]
        assert deprec, "Expected deprecation hint when OPENAI_VISION_MODEL is set"
        assert deprec[0].severity == "info"
        assert "VISION_MODEL" in deprec[0].message

    def test_no_deprecation_when_openai_vision_model_not_in_env(self):
        """When OPENAI_VISION_MODEL is not in env, no deprecation hint."""
        import os
        cfg = _make_config()
        real_getenv = os.getenv

        def mock_getenv(key, default=None):
            if key == "OPENAI_VISION_MODEL":
                return None
            return real_getenv(key, default)

        with patch("src.config.os.getenv", side_effect=mock_getenv):
            issues = cfg.validate_structured()
        deprec = [i for i in issues if i.field == "OPENAI_VISION_MODEL"]
        assert not deprec, "Should not report deprecation when OPENAI_VISION_MODEL is unset"


# ---------------------------------------------------------------------------
# Vision key validation
# ---------------------------------------------------------------------------

class TestVisionKeyValidation:
    def test_vision_model_set_no_key_is_warning(self):
        cfg = _make_config(
            vision_model="gemini/gemini-2.0-flash",
            llm_api_key="",
        )
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.field == "VISION_MODEL"]
        assert warn and warn[0].severity == "warning"

    def test_vision_model_set_with_key_no_warning(self):
        cfg = _make_config(
            vision_model="gemini/gemini-2.0-flash",
            llm_api_key="sk-test-key",
        )
        issues = cfg.validate_structured()
        assert not any(
            i.field == "VISION_MODEL" and i.severity == "warning" for i in issues
        )

    def test_no_vision_model_no_warning(self):
        """When VISION_MODEL is not set, no Vision key warning is raised."""
        cfg = _make_config(vision_model="", llm_api_key="")
        issues = cfg.validate_structured()
        assert not any(i.field == "VISION_MODEL" for i in issues)


# ---------------------------------------------------------------------------
# validate() backward compatibility
# ---------------------------------------------------------------------------

class TestValidateBackwardCompat:
    def test_returns_list_of_str(self):
        cfg = _make_config()
        result = cfg.validate()
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_empty_llm_model_message_in_validate(self):
        cfg = _make_config(llm_model="")
        messages = cfg.validate()
        assert any("LLM_MODEL" in m for m in messages)

    def test_messages_match_validate_structured(self):
        """validate() strings must be the message field of each ConfigIssue."""
        cfg = _make_config(llm_model_list=[])
        structured = cfg.validate_structured()
        plain = cfg.validate()
        assert plain == [i.message for i in structured]
