"""Global notification path: persist then push_existing; secrets stay out of the body."""

from types import SimpleNamespace

from finance_analysis.notification.service import NotificationResult  # pragma: allowlist secret
from finance_analysis.portfolio_risk.notify import push_after_commit, render_risk_message  # pragma: allowlist secret


def test_render_risk_message_includes_vwap_and_strips_google_secrets():
    title, body = render_risk_message(
        uid=1,
        snapshot_generation=3,
        results=[
            {
                "symbol": "600519.SH",
                "account_id": "a1",
                "position_id": "p1",
                "action": "REDUCE",
                "position_target": "1000",
                "vwap_mode": "PROXY",
                "reason": "相邻两根确认走弱",
                "legs": [
                    {
                        "role": "CORE",
                        "leg_id": "c1",
                        "quantity": "1000",
                        "target": "1000",
                        "active_stop": "96",
                        "stage": "A",
                    }
                ],
            }
        ],
    )
    assert "PROXY" in body
    assert "600519.SH" in body
    assert "refresh_token" not in body
    dirty_title, dirty = render_risk_message(
        uid=1,
        snapshot_generation=3,
        results=[{"symbol": "AAPL.US", "reason": "refresh_token=abc", "vwap_mode": "EXACT"}],
    )
    assert "abc" not in dirty
    assert dirty_title == "持仓风控"


def test_push_after_commit_does_not_create_another_in_app_row():
    calls = []

    class Fake(SimpleNamespace):
        def push_existing(self, content, **kwargs):
            calls.append((content, kwargs))
            return NotificationResult(notification_id=kwargs["notification_id"], push_attempted=True, push_sent=False)

        def send(self, *args, **kwargs):
            raise AssertionError("send() would duplicate in-app messages")

    result = push_after_commit(notification_id=44, title="持仓风控", content="body", service=Fake())
    assert result.notification_id == 44
    assert result.push_sent is False
    assert calls[0][1]["notification_id"] == 44
