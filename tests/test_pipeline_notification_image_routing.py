# -*- coding: utf-8 -*-
"""
Regression tests for pipeline email image routing with stock email groups.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.pipeline import StockAnalysisPipeline, NotificationChannel
from src.enums import ReportType


class _FakeNotifier:
    def __init__(self):
        self._markdown_to_image_channels = {"email"}
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(side_effect=self._generate_dashboard_report)
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=[NotificationChannel.EMAIL])
        self.get_channels_for_route = MagicMock(
            side_effect=lambda route_type, channels=None: list(
                channels if channels is not None else self.get_available_channels()
            )
        )
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self._send_email_with_inline_image = MagicMock(return_value=True)
        self.send_to_email = MagicMock(return_value=True)

    @staticmethod
    def _generate_dashboard_report(results):
        return "report:" + ",".join(r.code for r in results)


class TestPipelineEmailGroupImageRouting(unittest.TestCase):
    def _build_pipeline(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeNotifier()
        pipeline.config = SimpleNamespace(
            stock_email_groups=[
                (["000001"], ["group@example.com"]),
            ]
        )
        return pipeline

    def _make_results(self):
        return [
            SimpleNamespace(code="000001"),
            SimpleNamespace(code="600519"),
        ]

    @patch("src.md2img.markdown_to_image", return_value=b"png-bytes")
    def test_send_notifications_email_group_uses_inline_image_when_enabled(self, _mock_md2img):
        pipeline = self._build_pipeline()
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        self.assertEqual(pipeline.notifier._send_email_with_inline_image.call_count, 2)
        pipeline.notifier.send_to_email.assert_not_called()
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier._send_email_with_inline_image.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)

    @patch("src.md2img.markdown_to_image", return_value=None)
    def test_send_notifications_email_group_falls_back_to_text_when_image_unavailable(self, _mock_md2img):
        pipeline = self._build_pipeline()
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier._send_email_with_inline_image.assert_not_called()
        self.assertEqual(pipeline.notifier.send_to_email.call_count, 2)
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier.send_to_email.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)

    @patch("src.md2img.markdown_to_image", return_value=None)
    def test_send_notifications_email_group_failure_does_not_skip_later_group(self, _mock_md2img):
        pipeline = self._build_pipeline()
        pipeline.notifier.send_to_email.side_effect = [RuntimeError("group failed"), True]
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        self.assertEqual(pipeline.notifier.send_to_email.call_count, 2)
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier.send_to_email.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)


class _FakeRoutedNotifier:
    def __init__(self, routed_channels, image_channels=None, noise_should_send=True):
        self._markdown_to_image_channels = set(image_channels or [])
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(side_effect=self._generate_dashboard_report)
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(
            return_value=[
                NotificationChannel.TELEGRAM,
                NotificationChannel.EMAIL,
                NotificationChannel.NTFY,
            ]
        )
        self.get_channels_for_route = MagicMock(return_value=list(routed_channels))
        self.evaluate_noise_control = MagicMock(
            return_value=SimpleNamespace(
                should_send=noise_should_send,
                message="noise suppressed" if not noise_should_send else "",
            )
        )
        self.record_noise_control = MagicMock()
        self.release_noise_control = MagicMock()
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self._send_telegram_photo = MagicMock(return_value=True)
        self.send_to_telegram = MagicMock(return_value=True)
        self._send_email_with_inline_image = MagicMock(return_value=True)
        self.send_to_email = MagicMock(return_value=True)
        self.send_to_ntfy = MagicMock(return_value=True)

    @staticmethod
    def _generate_dashboard_report(results):
        return "report:" + ",".join(r.code for r in results)


class TestPipelineReportRouteFiltering(unittest.TestCase):
    def test_markdown_to_image_uses_route_filtered_channels(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.EMAIL],
            image_channels={"telegram"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_telegram.assert_not_called()

    def test_ntfy_route_uses_text_report_without_image_conversion(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.NTFY],
            image_channels={"ntfy"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_ntfy.assert_called_once_with("report:000001")
        pipeline.notifier._send_email_with_inline_image.assert_not_called()
        pipeline.notifier._send_telegram_photo.assert_not_called()

    def test_noise_suppression_happens_before_markdown_to_image(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.TELEGRAM],
            image_channels={"telegram"},
            noise_should_send=False,
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_telegram.assert_not_called()
        pipeline.notifier.record_noise_control.assert_not_called()

    def test_noise_reservation_released_when_pipeline_static_send_raises(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("send failed")
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_called_once()

    def test_channel_exception_does_not_skip_later_channel_and_records_noise(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM, NotificationChannel.EMAIL])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("telegram failed")
        pipeline.notifier.send_to_email.return_value = True
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.send_to_telegram.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.record_noise_control.assert_called_once()
        pipeline.notifier.release_noise_control.assert_not_called()

    def test_all_static_channel_failures_release_noise_reservation(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM, NotificationChannel.EMAIL])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("telegram failed")
        pipeline.notifier.send_to_email.return_value = False
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.send_to_telegram.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_called_once()


if __name__ == "__main__":
    unittest.main()
