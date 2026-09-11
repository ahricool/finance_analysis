# -*- coding: utf-8 -*-
"""
Unit tests for src.notification_sender module.

Tests sender classes in isolation (config, request shape, error handling).
Does not duplicate test_notification.py which tests NotificationService.send() flow.
"""
import json
import os
import sys
import unittest
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest import mock
from typing import Optional

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from finance_analysis.notification.config import NotificationConfig
from finance_analysis.notification.senders import (
    NtfySender,
    TelegramSender,
)


def _config(**overrides):
    """Minimal NotificationConfig for sender tests."""
    return NotificationConfig(**overrides)


def _response(status_code: int, json_body: Optional[dict] = None):
    resp = mock.MagicMock()
    resp.status_code = status_code
    if status_code == 200:
        resp.text = "ok"
    else:
        resp.text = "error"
    if json_body is not None:
        resp.json.return_value = json_body
    return resp




class TestNtfySender(unittest.TestCase):
    """Unit tests for NtfySender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("hello")

        self.assertFalse(result)

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_success_uses_json_publish_with_topic_endpoint(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            ntfy_url="https://ntfy.sh/fa-topic",
            ntfy_token="secret-token",
            webhook_verify_ssl=False,
        )
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("正文 **Markdown**", title="中文标题", timeout_seconds=5)

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], "https://ntfy.sh")
        call_kw = mock_post.call_args.kwargs
        self.assertEqual(
            call_kw["json"],
            {
                "topic": "fa-topic",
                "title": "中文标题",
                "message": "正文 **Markdown**",
                "markdown": True,
            },
        )
        self.assertEqual(call_kw["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(call_kw["timeout"], 5)
        self.assertFalse(call_kw["verify"])

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_supports_self_hosted_path_prefix(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(ntfy_url="https://example.com/ntfy/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body", title="title")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_args.args[0], "https://example.com/ntfy")
        self.assertEqual(mock_post.call_args.kwargs["json"]["topic"], "fa-topic")

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_returns_false_when_url_has_no_topic(self, mock_post):
        cfg = _config(ntfy_url="https://ntfy.sh")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_returns_false_when_url_scheme_is_not_http(self, mock_post):
        cfg = _config(ntfy_url="ftp://ntfy.example/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_http_error_returns_false(self, mock_post):
        mock_post.return_value = _response(500)
        cfg = _config(ntfy_url="https://ntfy.sh/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)

    @mock.patch("finance_analysis.notification.senders.ntfy.requests.post")
    def test_send_timeout_does_not_log_token_value(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("secret-token")
        cfg = _config(ntfy_url="https://ntfy.sh/fa-topic", ntfy_token="secret-token")
        sender = NtfySender(cfg)

        with self.assertLogs("finance_analysis.notification.senders.ntfy", level="ERROR") as captured:
            result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        self.assertNotIn("secret-token", "\n".join(captured.output))






class TestTelegramSender(unittest.TestCase):
    """Unit tests for TelegramSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertFalse(result)

    @mock.patch("finance_analysis.notification.senders.telegram.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"ok": True})
        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertTrue(result)
        self.assertIn("sendMessage", mock_post.call_args[0][0])

    @mock.patch("finance_analysis.notification.senders.telegram.requests.post")
    def test_send_retries_plain_text_when_markdown_http_400(self, mock_post):
        markdown_error = _response(400)
        markdown_error.text = (
            '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'
        )
        plain_text_success = _response(200, {"ok": True})
        mock_post.side_effect = [markdown_error, plain_text_success]

        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("*ST宝实")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0][1]["json"]
        second_payload = mock_post.call_args_list[1][1]["json"]
        self.assertEqual(first_payload["parse_mode"], "Markdown")
        self.assertNotIn("parse_mode", second_payload)
        self.assertEqual(second_payload["text"], "*ST宝实")

    @mock.patch("finance_analysis.notification.senders.telegram.requests.post")
    def test_send_plain_text_fallback_handles_non_json_200(self, mock_post):
        markdown_error = _response(400)
        markdown_error.text = (
            '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'
        )
        plain_text_non_json = _response(200)
        plain_text_non_json.text = "upstream proxy error"
        plain_text_non_json.json.side_effect = ValueError("invalid json")
        mock_post.side_effect = [markdown_error, plain_text_non_json]

        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("*ST宝实")

        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
