# -*- coding: utf-8 -*-
"""Tests for the Celery Beat Redis heartbeat health check."""

from __future__ import annotations

from unittest.mock import patch

from finance_analysis.tasks.celery import heartbeat


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.last_ttl = None

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.last_ttl = ex

    def get(self, key):
        return self.store.get(key)


def test_write_heartbeat_sets_value_with_ttl():
    client = _FakeRedis()
    assert heartbeat.write_beat_heartbeat(client) is True
    assert heartbeat.HEARTBEAT_KEY in client.store
    assert client.last_ttl == heartbeat.HEARTBEAT_TTL_SECONDS


def test_read_status_active_when_heartbeat_present():
    client = _FakeRedis()
    heartbeat.write_beat_heartbeat(client)
    assert heartbeat.read_beat_status(client) == "active"


def test_read_status_unavailable_when_heartbeat_missing():
    client = _FakeRedis()
    assert heartbeat.read_beat_status(client) == "unavailable"


def test_read_status_unavailable_when_no_client():
    with patch.object(heartbeat, "_redis_client", return_value=None):
        assert heartbeat.read_beat_status() == "unavailable"
