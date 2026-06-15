# -*- coding: utf-8 -*-
"""Compatibility assertions for market review runtime assembly."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.market_review_runtime import build_market_review_runtime, has_configured_llm_runtime


class TestMarketReviewRuntimeCompatibility(unittest.TestCase):
    @staticmethod
    def _base_config() -> SimpleNamespace:
        return SimpleNamespace(
            llm_model="",
            llm_api_key="",
            llm_base_url=None,
            llm_fallback_models=[],
            bocha_api_keys=None,
            tavily_api_keys=None,
            anspire_api_keys=None,
            brave_api_keys=None,
            serpapi_api_keys=None,
            minimax_api_keys=None,
            searxng_base_urls=None,
            searxng_public_instances_enabled=True,
            news_max_age_days=3,
            news_strategy_profile="short",
            has_search_capability_enabled=lambda: False,
        )

    def test_build_market_review_runtime_with_unified_llm_config(self) -> None:
        config = self._base_config()
        config.llm_model = "openai/gpt-5.5"
        config.llm_api_key = "openai-key"
        notifier = MagicMock()
        analyzer = MagicMock()
        analyzer.is_available.return_value = True

        import src.analyzer
        import src.notification
        import src.search_service

        with patch.object(src.analyzer, "GeminiAnalyzer", return_value=analyzer) as analyzer_cls, \
             patch.object(src.notification, "NotificationService", return_value=notifier) as notifier_cls, \
             patch.object(src.search_service, "SearchService") as search_cls:
            runtime_notifier, runtime_analyzer, runtime_search = build_market_review_runtime(config)

        notifier_cls.assert_called_once_with(source_message=None)
        analyzer_cls.assert_called_once_with(config=config)
        search_cls.assert_not_called()
        self.assertIs(runtime_notifier, notifier)
        self.assertIs(runtime_analyzer, analyzer)
        self.assertIsNone(runtime_search)

    def test_has_configured_llm_runtime_returns_false_without_model_or_key(self) -> None:
        config = self._base_config()
        self.assertFalse(has_configured_llm_runtime(config))

    def test_has_configured_llm_runtime_requires_model_and_key(self) -> None:
        base = self._base_config()
        test_configs = [
            ("model_only", {"llm_model": "openai/gpt-5.5", "llm_api_key": ""}),
            ("key_only", {"llm_model": "", "llm_api_key": "sk-test"}),
            ("configured", {"llm_model": "openai/gpt-5.5", "llm_api_key": "sk-test"}),
            ("ollama_local", {"llm_model": "ollama/qwen3:8b", "llm_api_key": "", "llm_base_url": "http://localhost:11434"}),
        ]

        for name, updates in test_configs:
            with self.subTest(case=name):
                config = SimpleNamespace(**vars(base))
                for key, value in updates.items():
                    setattr(config, key, value)
                expected = name in {"configured", "ollama_local"}
                self.assertEqual(has_configured_llm_runtime(config), expected)
