# -*- coding: utf-8 -*-
"""Tests for notification route channel parsing."""

from src.notification_routing import ROUTABLE_NOTIFICATION_CHANNELS, split_notification_route_channels


def test_ntfy_is_routable_notification_channel() -> None:
    valid, invalid = split_notification_route_channels(["telegram", "ntfy", "not-a-channel"])

    assert "ntfy" in ROUTABLE_NOTIFICATION_CHANNELS
    assert "telegram" in ROUTABLE_NOTIFICATION_CHANNELS
    assert valid == ["telegram", "ntfy"]
    assert invalid == ["not-a-channel"]


def test_removed_channels_are_not_routable() -> None:
    valid, invalid = split_notification_route_channels(["wechat", "feishu", "discord", "ntfy"])

    assert valid == ["ntfy"]
    assert set(invalid) == {"wechat", "feishu", "discord"}
