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

from src.config import Config
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    EmailSender,
    NtfySender,
    TelegramSender,
)


def _config(**overrides):
    """Minimal Config for sender tests."""
    return Config(database_url=os.environ["DATABASE_URL"], **overrides)


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


class TestEmailSender(unittest.TestCase):
    """Unit tests for EmailSender (config and receiver logic; send path covered via service)."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = EmailSender(cfg)
        result = sender.send_to_email("body")
        self.assertFalse(result)

    def test_get_receivers_for_stocks_no_groups_returns_default(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com", "c@qq.com"],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["000001"]),
            ["b@qq.com", "c@qq.com"],
        )

    def test_get_receivers_for_stocks_with_matching_group(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[(["000001", "600519"], ["group1@qq.com"])],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["000001"]),
            ["group1@qq.com"],
        )

    def test_get_receivers_for_stocks_no_match_falls_back_to_default(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[(["000001"], ["group@qq.com"])],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["999999"]),
            ["default@qq.com"],
        )

    def test_get_all_email_receivers_returns_union(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[
                (["000001"], ["g1@qq.com"]),
                (["600519"], ["g2@qq.com"]),
            ],
        )
        sender = EmailSender(cfg)
        receivers = sender.get_all_email_receivers()
        self.assertIn("g1@qq.com", receivers)
        self.assertIn("g2@qq.com", receivers)
        self.assertIn("default@qq.com", receivers)

    @mock.patch("smtplib.SMTP_SSL")
    def test_send_to_email_encodes_non_ascii_sender_name(self, mock_smtp_ssl):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com"],
            email_sender_name="Finance Analysis 分析助手",
        )
        sender = EmailSender(cfg)

        result = sender.send_to_email("body", subject="测试主题")

        self.assertTrue(result)
        server = mock_smtp_ssl.return_value
        server.send_message.assert_called_once()
        msg = server.send_message.call_args[0][0]
        realname, addr = parseaddr(msg["From"])
        self.assertEqual(addr, "a@qq.com")
        self.assertEqual(
            str(make_header(decode_header(realname))),
            "Finance Analysis 分析助手",
        )
        server.quit.assert_called_once()

    @mock.patch("smtplib.SMTP_SSL")
    def test_send_image_email_encodes_non_ascii_sender_name(self, mock_smtp_ssl):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com"],
            email_sender_name="Finance Analysis 分析助手",
        )
        sender = EmailSender(cfg)

        result = sender._send_email_with_inline_image(b"PNG_BYTES", receivers=["b@qq.com"])

        self.assertTrue(result)
        server = mock_smtp_ssl.return_value
        server.send_message.assert_called_once()
        msg = server.send_message.call_args[0][0]
        realname, addr = parseaddr(msg["From"])
        self.assertEqual(addr, "a@qq.com")
        self.assertEqual(
            str(make_header(decode_header(realname))),
            "Finance Analysis 分析助手",
        )
        server.quit.assert_called_once()


class TestNtfySender(unittest.TestCase):
    """Unit tests for NtfySender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("hello")

        self.assertFalse(result)

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
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

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_supports_self_hosted_path_prefix(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(ntfy_url="https://example.com/ntfy/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body", title="title")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_args.args[0], "https://example.com/ntfy")
        self.assertEqual(mock_post.call_args.kwargs["json"]["topic"], "fa-topic")

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_returns_false_when_url_has_no_topic(self, mock_post):
        cfg = _config(ntfy_url="https://ntfy.sh")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_returns_false_when_url_scheme_is_not_http(self, mock_post):
        cfg = _config(ntfy_url="ftp://ntfy.example/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_http_error_returns_false(self, mock_post):
        mock_post.return_value = _response(500)
        cfg = _config(ntfy_url="https://ntfy.sh/fa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_timeout_does_not_log_token_value(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("secret-token")
        cfg = _config(ntfy_url="https://ntfy.sh/fa-topic", ntfy_token="secret-token")
        sender = NtfySender(cfg)

        with self.assertLogs("src.notification_sender.ntfy_sender", level="ERROR") as captured:
            result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        self.assertNotIn("secret-token", "\n".join(captured.output))


class TestAstrbotSender(unittest.TestCase):
    """Unit tests for AstrbotSender."""

    def test_send_returns_false_when_no_url(self):
        cfg = _config()
        sender = AstrbotSender(cfg)
        result = sender.send_to_astrbot("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.astrbot_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(astrbot_url="https://astrbot.example/api")
        sender = AstrbotSender(cfg)
        result = sender.send_to_astrbot("hello")
        self.assertTrue(result)
        self.assertEqual(mock_post.call_args[0][0], "https://astrbot.example/api")


class TestCustomWebhookSender(unittest.TestCase):
    """Unit tests for CustomWebhookSender."""

    def test_send_returns_false_when_no_urls(self):
        cfg = _config()
        sender = CustomWebhookSender(cfg)
        result = sender.send_to_custom("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_success_payload_has_text_and_content(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(custom_webhook_urls=["https://example.com/webhook"])
        sender = CustomWebhookSender(cfg)
        result = sender.send_to_custom("hello")
        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertIn("hello", body)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_returns_true_when_one_custom_webhook_succeeds(self, mock_post):
        mock_post.side_effect = [_response(500), _response(200)]
        cfg = _config(
            custom_webhook_urls=[
                "https://example.com/fail",
                "https://example.com/ok",
            ]
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_custom_webhooks_returns_ordered_attempts(self, mock_post):
        mock_post.side_effect = [_response(500), _response(200)]
        cfg = _config(
            custom_webhook_urls=[
                "https://example.com/fail?access_token=secret",
                "https://example.com/ok",
            ]
        )
        sender = CustomWebhookSender(cfg)

        attempts = sender.test_custom_webhooks("hello", timeout_seconds=7)

        self.assertEqual(len(attempts), 2)
        self.assertFalse(attempts[0]["success"])
        self.assertTrue(attempts[1]["success"])
        self.assertEqual(attempts[0]["http_status"], 500)
        self.assertEqual(mock_post.call_args_list[0].kwargs["timeout"], 7)

    def test_bark_payload_shape_is_stable(self):
        sender = CustomWebhookSender(_config())

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "hello")

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "body": "hello",
                "group": "stock",
            },
        )

    def test_bark_payload_truncates_long_content(self):
        sender = CustomWebhookSender(_config())

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "x" * 5000)

        self.assertEqual(len(payload["body"]), 4000)
        self.assertEqual(payload["body"], "x" * 4000)

    def test_custom_body_template_overrides_bark_auto_payload(self):
        cfg = _config(
            custom_webhook_body_template=(
                '{"title":$title_json,"body":$content_json,"sound":"bell"}'
            ),
        )
        sender = CustomWebhookSender(cfg)

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "hello")

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "body": "hello",
                "sound": "bell",
            },
        )
        self.assertNotIn("group", payload)

    def test_custom_body_template_json_placeholders_escape_content(self):
        cfg = _config(
            custom_webhook_body_template=(
                '{"title":$title_json,"content":$content_json}'
            ),
        )
        sender = CustomWebhookSender(cfg)

        payload = sender._build_custom_webhook_payload(
            "https://example.com/webhook",
            'line 1\nline "2"',
        )

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "content": 'line 1\nline "2"',
            },
        )

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_uses_custom_body_template(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='{"msg_type":"text","content":$content_json}',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom('hello "world"')

        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertEqual(
            json.loads(body),
            {"msg_type": "text", "content": 'hello "world"'},
        )

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_invalid_custom_body_template_falls_back(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='{"content": $content',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertIn("hello", body)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_non_object_custom_body_template_falls_back(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='["not", "object"]',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        body = json.loads(mock_post.call_args[1]["data"].decode("utf-8"))
        self.assertEqual(body["content"], "hello")
        self.assertEqual(body["message"], "hello")


class TestTelegramSender(unittest.TestCase):
    """Unit tests for TelegramSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"ok": True})
        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertTrue(result)
        self.assertIn("sendMessage", mock_post.call_args[0][0])

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
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

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
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
