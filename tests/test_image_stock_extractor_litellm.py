# -*- coding: utf-8 -*-
"""Tests for image stock extraction through the unified LLM client."""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.services.image_stock_extractor import (
    VISION_API_TIMEOUT,
    _call_litellm_vision,
    _parse_codes_from_text,
    _parse_items_from_text,
    _resolve_vision_model,
    extract_stock_codes_from_image,
)


def _cfg(**kwargs) -> Config:
    defaults = dict(
        llm_model="openai/gpt-5.5",
        llm_api_key="sk-test-key",
        llm_base_url=None,
        vision_model="",
        database_url=os.environ["DATABASE_URL"],
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _make_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 20


class TestResolveVisionModel:
    def test_uses_vision_model_first(self):
        cfg = _cfg(vision_model="openai/gpt-4o", llm_model="openai/gpt-5.5")
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
            assert _resolve_vision_model() == "openai/gpt-4o"

    def test_falls_back_to_llm_model(self):
        cfg = _cfg(vision_model="", llm_model="openai/gpt-5.5")
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
            assert _resolve_vision_model() == "openai/gpt-5.5"

    def test_returns_empty_without_model(self):
        cfg = _cfg(vision_model="", llm_model="")
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
            assert _resolve_vision_model() == ""


class TestCallVision:
    def test_calls_unified_vision_client(self):
        cfg = _cfg(vision_model="openai/gpt-4o")
        result = MagicMock(text='[{"code":"600519","name":"贵州茅台","confidence":"high"}]')
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg), \
             patch("src.services.image_stock_extractor.LLMClient") as client_cls:
            client = client_cls.return_value
            client.complete_vision.return_value = result

            text = _call_litellm_vision("base64data", "image/jpeg")

        assert text == result.text
        client_cls.assert_called_once_with(config=cfg, models_to_try=["openai/gpt-4o"])
        request = client.complete_vision.call_args.args[0]
        assert request.max_tokens == 1024
        assert request.timeout == VISION_API_TIMEOUT
        assert request.call_type == "vision_stock_extraction"

    def test_raises_when_model_not_configured(self):
        cfg = _cfg(vision_model="", llm_model="")
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
            with pytest.raises(ValueError, match="未配置 Vision 模型"):
                _call_litellm_vision("b64", "image/jpeg")

    def test_raises_when_client_returns_empty(self):
        cfg = _cfg(vision_model="openai/gpt-4o")
        with patch("src.services.image_stock_extractor.get_config", return_value=cfg), \
             patch("src.services.image_stock_extractor.LLMClient") as client_cls:
            client_cls.return_value.complete_vision.return_value = MagicMock(text="")
            with pytest.raises(ValueError, match="Vision LLM returned empty response"):
                _call_litellm_vision("b64", "image/jpeg")


class TestParseCodesFromText:
    def test_parses_json_array(self):
        assert _parse_codes_from_text('["600519", "300750", "AAPL"]') == ["600519", "300750", "AAPL"]

    def test_parses_fallback_from_plain_text(self):
        codes = _parse_codes_from_text("关注 600519、300750 和 AAPL。")
        assert "600519" in codes
        assert "300750" in codes
        assert "AAPL" in codes


class TestParseItemsFromText:
    def test_parses_new_format(self):
        text = '[{"code":"600519","name":"贵州茅台","confidence":"high"}]'
        assert _parse_items_from_text(text) == [("600519", "贵州茅台", "high")]

    def test_fallback_to_legacy_format(self):
        assert _parse_items_from_text('["600519", "300750"]') == [
            ("600519", None, "medium"),
            ("300750", None, "medium"),
        ]

    def test_uses_json_repair_when_json_invalid(self):
        text = '[{"code":"600519","name":"贵州茅台","confidence":"high"'
        assert _parse_items_from_text(text) == [("600519", "贵州茅台", "high")]


class TestExtractStockCodesFromImage:
    def test_returns_items_and_raw(self):
        jpeg = _make_jpeg_bytes()
        with patch(
            "src.services.image_stock_extractor._call_litellm_vision",
            return_value='[{"code":"600519","name":"贵州茅台","confidence":"high"}]',
        ):
            items, raw = extract_stock_codes_from_image(jpeg, "image/jpeg")
        assert items == [("600519", "贵州茅台", "high")]
        assert isinstance(raw, str)

    def test_rejects_unsupported_mime(self):
        with pytest.raises(ValueError, match="不支持的图片类型"):
            extract_stock_codes_from_image(_make_jpeg_bytes(), "image/bmp")

    def test_rejects_empty_bytes(self):
        with pytest.raises(ValueError, match="图片内容为空"):
            extract_stock_codes_from_image(b"", "image/jpeg")

    def test_rejects_wrong_magic_bytes(self):
        fake = b"\x00\x00\x00" + b"\x00" * 20
        with pytest.raises(ValueError):
            extract_stock_codes_from_image(fake, "image/jpeg")

    def test_wraps_vision_error_message(self):
        jpeg = _make_jpeg_bytes()
        with patch(
            "src.services.image_stock_extractor._call_litellm_vision",
            side_effect=RuntimeError("network down"),
        ):
            with pytest.raises(ValueError, match="Vision API 调用失败"):
                extract_stock_codes_from_image(jpeg, "image/jpeg")
