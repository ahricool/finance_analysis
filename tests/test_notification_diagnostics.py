# -*- coding: utf-8 -*-
"""Tests for read-only notification diagnostics."""

import os
import unittest

from src.config import Config
from src.notification import NotificationChannel
from src.services.notification_diagnostics import (
    CHANNEL_SPECS,
    KEY_SPECS,
    NotificationDiagnosticResult,
    P3_ROUTE_ENV_KEYS,
    P4_NOISE_ENV_KEYS,
    format_notification_diagnostics,
    run_notification_diagnostics,
)


def _config(**overrides) -> Config:
    return Config(database_url=os.environ["DATABASE_URL"], **overrides)


class NotificationDiagnosticsTestCase(unittest.TestCase):
    def test_channel_specs_cover_all_non_unknown_enum_channels(self):
        spec_channels = {spec.channel for spec in CHANNEL_SPECS}
        expected = {
            channel.value
            for channel in NotificationChannel
            if channel is not NotificationChannel.UNKNOWN
        }

        self.assertTrue(expected.issubset(spec_channels))
        self.assertIn(NotificationChannel.UNKNOWN.value, spec_channels)

    def test_key_specs_include_minimal_and_advanced_keys(self):
        key_tiers = {(spec.key, spec.tier) for spec in KEY_SPECS}

        self.assertIn(("ASTRBOT_URL", "minimal"), key_tiers)
        self.assertIn(("ASTRBOT_TOKEN", "advanced"), key_tiers)
        self.assertIn(("NTFY_URL", "minimal"), key_tiers)
        self.assertIn(("NTFY_TOKEN", "advanced"), key_tiers)
        self.assertIn(("CUSTOM_WEBHOOK_BODY_TEMPLATE", "advanced"), key_tiers)
        self.assertIn(("WEBHOOK_VERIFY_SSL", "advanced"), key_tiers)
        for key in P3_ROUTE_ENV_KEYS:
            self.assertIn((key, "advanced"), key_tiers)
        for key in P4_NOISE_ENV_KEYS:
            self.assertIn((key, "advanced"), key_tiers)

    def test_empty_config_reports_no_channels_as_error(self):
        result = run_notification_diagnostics(_config())

        self.assertIsInstance(result, NotificationDiagnosticResult)
        self.assertEqual(result.configured_channels, ())
        self.assertFalse(result.ok)
        self.assertIn("no_channels_configured", {item.code for item in result.errors})

        output = format_notification_diagnostics(result)
        self.assertIn("已配置渠道: 0 个", output)
        self.assertIn("0 个通知渠道已配置", output)

    def test_partial_config_reports_missing_pair(self):
        result = run_notification_diagnostics(_config(telegram_bot_token="TOKEN"))

        self.assertFalse(result.ok)
        self.assertIn("TELEGRAM_CHAT_ID", {item.key for item in result.errors})

    def test_ntfy_url_without_topic_reports_error(self):
        result = run_notification_diagnostics(_config(ntfy_url="https://ntfy.sh"))

        self.assertFalse(result.ok)
        self.assertNotIn("ntfy", result.configured_channels)
        self.assertIn("invalid_ntfy_url", {item.code for item in result.errors})
        self.assertIn("NTFY_URL", {item.key for item in result.errors})

    def test_ntfy_url_with_unsupported_scheme_reports_error(self):
        result = run_notification_diagnostics(_config(ntfy_url="ftp://ntfy.example/fa-topic"))

        self.assertFalse(result.ok)
        self.assertNotIn("ntfy", result.configured_channels)
        self.assertIn("invalid_ntfy_url", {item.code for item in result.errors})
        self.assertIn("NTFY_URL", {item.key for item in result.errors})


if __name__ == "__main__":
    unittest.main()
