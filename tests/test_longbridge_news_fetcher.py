# -*- coding: utf-8 -*-
"""Unit tests for LongbridgeNewsFetcher."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from finance_analysis.integrations.market_data.providers.longbridge.news import (
    LongbridgeNewsFetcher,
    LongbridgeNewsRecord,
    _canonical_news_url,
    _normalize_news_item,
    news_records_to_search_response,
)


class _FakeNewsItem:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestLongbridgeNewsNormalization(unittest.TestCase):
    def test_canonical_news_url_uses_longbridge_id_when_missing(self):
        self.assertEqual(
            _canonical_news_url("279528757", ""),
            "https://longbridge.com/news/279528757",
        )

    def test_normalize_news_item_parses_timestamp(self):
        item = _FakeNewsItem(
            id="279528757",
            title="Apple launches new product",
            description="Summary text",
            url="https://longbridge.com/news/279528757",
            published_at="1773805586",
            comments_count=1,
            likes_count=2,
            shares_count=3,
        )

        record = _normalize_news_item(item)

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.news_id, "279528757")
        self.assertEqual(record.title, "Apple launches new product")
        self.assertEqual(record.published_at, datetime.fromtimestamp(1773805586, tz=timezone.utc))

    def test_news_records_to_search_response_provider(self):
        records = [
            LongbridgeNewsRecord(
                news_id="1",
                title="Headline",
                description="Body",
                url="https://longbridge.com/news/1",
                published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            )
        ]
        response = news_records_to_search_response("AAPL", records)

        self.assertEqual(response.provider, "longbridge")
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].source, "longbridge")


class TestLongbridgeNewsFetcher(unittest.TestCase):
    def setUp(self):
        self.quote_fetcher = MagicMock()
        self.quote_fetcher._is_available.return_value = True
        self.fetcher = LongbridgeNewsFetcher(self.quote_fetcher)

    def test_fetch_news_returns_empty_without_credentials(self):
        self.quote_fetcher._is_available.return_value = False

        records = self.fetcher.fetch_news("AAPL")

        self.assertEqual(records, [])

    @patch("finance_analysis.integrations.market_data.providers.longbridge.news.build_longbridge_config")
    def test_build_config_does_not_initialize_quote_context(self, build_config):
        config = object()
        build_config.return_value = config

        assert self.fetcher._build_config() is config

        self.quote_fetcher._get_ctx.assert_not_called()

    def test_close_releases_and_detaches_content_context(self):
        context = MagicMock()
        self.fetcher._ctx = context
        self.fetcher._config = object()

        self.fetcher.close()

        context.close.assert_called_once_with()
        self.assertIsNone(self.fetcher._ctx)
        self.assertIsNone(self.fetcher._config)

    @patch(
        "finance_analysis.integrations.market_data.providers.longbridge.news._to_longbridge_symbol",
        return_value="AAPL.US",
    )
    def test_fetch_news_normalizes_sdk_items(self, _mock_symbol):
        fake_ctx = MagicMock()
        fake_ctx.news.return_value = [
            _FakeNewsItem(
                id="1",
                title="NVDA beats estimates",
                description="Earnings beat",
                url="https://longbridge.com/news/1",
                published_at="1773805586",
            )
        ]
        self.fetcher._get_ctx = MagicMock(return_value=fake_ctx)

        records = self.fetcher.fetch_news("NVDA", limit=3)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "NVDA beats estimates")
        fake_ctx.news.assert_called_once_with("AAPL.US")

    @patch(
        "finance_analysis.integrations.market_data.providers.longbridge.news._to_longbridge_symbol",
        return_value="AAPL.US",
    )
    def test_fetch_and_save_news_persists_with_dedup(self, _mock_symbol):
        fake_ctx = MagicMock()
        fake_ctx.news.return_value = [
            _FakeNewsItem(
                id="1",
                title="NVDA beats estimates",
                description="Earnings beat",
                url="https://longbridge.com/news/1",
                published_at="1773805586",
            )
        ]
        self.fetcher._get_ctx = MagicMock(return_value=fake_ctx)

        with patch("finance_analysis.database.DatabaseManager.get_instance") as mock_db_getter:
            mock_db = MagicMock()
            mock_db_getter.return_value = mock_db

            records = self.fetcher.fetch_and_save_news(
                "NVDA",
                name="英伟达",
                query_id="us_intraday_test",
            )

            self.assertEqual(len(records), 1)
            mock_db.save_news_intel.assert_called_once()
            kwargs = mock_db.save_news_intel.call_args.kwargs
            self.assertEqual(kwargs["code"], "NVDA")
            self.assertEqual(kwargs["dimension"], "intraday_news")
            self.assertEqual(kwargs["response"].provider, "longbridge")


if __name__ == "__main__":
    unittest.main()
