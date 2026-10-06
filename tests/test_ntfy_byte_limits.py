"""Verify actual HTTP bytes, including Unicode, JSON escapes and multipart labels."""

import json
from unittest.mock import Mock, patch

import pytest

from finance_analysis.notification.config import NotificationConfig
from finance_analysis.notification.senders.ntfy import NtfySender, _publish_bodies, JSON_LIMIT_BYTES, MESSAGE_LIMIT_BYTES


@pytest.mark.parametrize("content", ["中文🙂" * 2000, '\"\\\n' * 3000, "word " * 3000, "汉" * 1365, "a" * 4096])
def test_parts_preserve_content_and_bound_actual_wire_bytes(content):
    bodies = _publish_bodies("test-topic", "标题🙂", content)
    messages = []
    for index, body in enumerate(bodies, 1):
        payload = json.loads(body)
        assert len(body) <= JSON_LIMIT_BYTES
        assert len(payload["message"].encode("utf-8")) <= MESSAGE_LIMIT_BYTES
        prefix = f"[{index}/{len(bodies)}]\n" if len(bodies) > 1 else ""
        assert payload["message"].startswith(prefix)
        messages.append(payload["message"][len(prefix):])
    assert "".join(messages) == content


def test_escape_heavy_metadata_is_included_in_json_limit():
    bodies = _publish_bodies("test-topic", '\"' * 900, '\"' * 3900)
    assert len(bodies) > 1
    assert all(len(body) <= JSON_LIMIT_BYTES for body in bodies)


def test_later_part_failure_is_not_success_and_does_not_resend_first_part():
    sender = NtfySender(NotificationConfig(ntfy_url="https://ntfy.example/test"))
    responses = [Mock(status_code=200), Mock(status_code=413, text="too large")]
    with patch("finance_analysis.notification.senders.ntfy.requests.post", side_effect=responses) as post:
        assert sender.send_to_ntfy("汉" * 4000) is False
    assert post.call_count == 2
    assert "json" not in post.call_args.kwargs
    assert isinstance(post.call_args.kwargs["data"], bytes)
