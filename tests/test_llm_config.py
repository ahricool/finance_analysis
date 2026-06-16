# -*- coding: utf-8 -*-
"""Tests for unified LiteLLM configuration and client."""

import os
import unittest
from unittest.mock import patch

from src.config import Config, get_effective_agent_models_to_try, get_effective_agent_primary_model
from src.llm_client import (
    LLMConfigError,
    build_completion_kwargs,
    completion_with_fallback,
    get_models_to_try,
    validate_llm_config,
)


class UnifiedLLMConfigTestCase(unittest.TestCase):
    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_stock_email_groups", return_value=[])
    def test_loads_unified_llm_env(self, _mock_groups, _mock_setup_env) -> None:
        env = {
            "LLM_MODEL": "openai/gpt-5.5",
            "LLM_BASE_URL": "https://proxy.example/v1",
            "LLM_API_KEY": "sk-test-key",
            "LLM_TEMPERATURE": "0.4",
            "LLM_FALLBACK_MODELS": "openai/gpt-4.1,anthropic/claude-sonnet-4-6",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_model, "openai/gpt-5.5")
        self.assertEqual(config.llm_base_url, "https://proxy.example/v1")
        self.assertEqual(config.llm_api_key, "sk-test-key")
        self.assertEqual(config.llm_temperature, 0.4)
        self.assertEqual(
            config.llm_fallback_models,
            ["openai/gpt-4.1", "anthropic/claude-sonnet-4-6"],
        )
        self.assertEqual(config.litellm_model, "openai/gpt-5.5")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_stock_email_groups", return_value=[])
    def test_legacy_litellm_aliases_are_ignored(self, _mock_groups, _mock_setup_env) -> None:
        env = {
            "LITELLM_MODEL": "gemini/gemini-3.1-pro-preview",
            "GEMINI_API_KEY": "gemini-test-key",
            "LITELLM_FALLBACK_MODELS": "gemini/gemini-3-flash-preview",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_model, "")
        self.assertIsNone(config.llm_api_key)
        self.assertEqual(config.llm_fallback_models, [])

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_stock_email_groups", return_value=[])
    def test_agent_model_inherits_primary(self, _mock_groups, _mock_setup_env) -> None:
        env = {
            "LLM_MODEL": "openai/gpt-5.5",
            "LLM_API_KEY": "sk-test-key",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(get_effective_agent_primary_model(config), "openai/gpt-5.5")
        self.assertEqual(get_effective_agent_models_to_try(config), ["openai/gpt-5.5"])


class LiteLLMClientTestCase(unittest.TestCase):
    def _config(self) -> Config:
        return Config(
            llm_model="openai/gpt-5.5",
            llm_base_url="https://proxy.example/v1",
            llm_api_key="sk-test-key",
            llm_temperature=0.7,
            llm_fallback_models=["openai/gpt-4.1"],
        )

    def test_build_completion_kwargs_passes_api_base_and_key(self) -> None:
        kwargs = build_completion_kwargs(
            self._config(),
            "openai/gpt-5.5",
            [{"role": "user", "content": "hi"}],
        )

        self.assertEqual(kwargs["model"], "openai/gpt-5.5")
        self.assertEqual(kwargs["api_key"], "sk-test-key")
        self.assertEqual(kwargs["api_base"], "https://proxy.example/v1")
        self.assertNotIn("chat/completions", kwargs["api_base"])

    def test_missing_model_raises_clear_error(self) -> None:
        config = Config(llm_api_key="sk-test-key")
        with self.assertRaisesRegex(LLMConfigError, "LLM_MODEL"):
            validate_llm_config(config)

    def test_missing_api_key_raises_clear_error(self) -> None:
        config = Config(llm_model="openai/gpt-5.5")
        with self.assertRaisesRegex(LLMConfigError, "LLM_API_KEY"):
            validate_llm_config(config)

    def test_get_models_to_try_includes_fallbacks(self) -> None:
        self.assertEqual(
            get_models_to_try(self._config()),
            ["openai/gpt-5.5", "openai/gpt-4.1"],
        )

    @patch("src.llm.client.completion")
    def test_completion_with_fallback_retries_next_model(self, mock_completion) -> None:
        mock_completion.side_effect = [RuntimeError("primary failed"), object()]

        response, model = completion_with_fallback(
            self._config(),
            [{"role": "user", "content": "hi"}],
        )

        self.assertIsNotNone(response)
        self.assertEqual(model, "openai/gpt-4.1")
        self.assertEqual(mock_completion.call_count, 2)
        first_model = mock_completion.call_args_list[0].args[1]
        second_model = mock_completion.call_args_list[1].args[1]
        self.assertEqual(first_model, "openai/gpt-5.5")
        self.assertEqual(second_model, "openai/gpt-4.1")

    @patch("litellm.completion")
    def test_single_model_completion(self, mock_completion) -> None:
        from src.llm_client import completion

        mock_completion.return_value = {"ok": True}
        result = completion(
            self._config(),
            "openai/gpt-5.5",
            [{"role": "user", "content": "hi"}],
        )

        self.assertEqual(result, {"ok": True})
        call_kwargs = mock_completion.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "openai/gpt-5.5")
        self.assertEqual(call_kwargs["api_key"], "sk-test-key")
        self.assertEqual(call_kwargs["api_base"], "https://proxy.example/v1")


if __name__ == "__main__":
    unittest.main()
