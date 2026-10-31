"""Private reports must never use another user's or deployment-wide recipient by default."""

from types import SimpleNamespace as NS

from finance_analysis.holdings_review.notification import push_review


def test_ordinary_user_without_profile_does_not_send_private_report_globally():
    calls = []
    users = NS(get_by_uid=lambda uid: NS(extra={}, role="user"))
    push_review(7, 11, "CN", "2026-10-30", "private", users=users, factory=lambda **kwargs: calls.append(kwargs))
    assert not calls


def test_owner_profile_recipients_receive_only_the_existing_message():
    calls = []
    user = NS(
        role="user",
        extra={
            "notification": {
                "telegram": [{"bot_token": "test-token", "chat_id": "owner"}],
                "ntfy": [{"url": "https://example.com/private-topic"}],
            }
        },
    )

    def factory(config):
        return NS(push_existing=lambda content, **kwargs: calls.append((config, content, kwargs)))

    push_review(7, 11, "CN", "2026-10-30", "one markdown", users=NS(get_by_uid=lambda uid: user), factory=factory)
    assert len(calls) == 2
    assert all(content == "one markdown" and kwargs["notification_id"] == 11 for _, content, kwargs in calls)
    assert calls[0][0].telegram_chat_id == "owner" and calls[0][0].ntfy_url is None
    assert calls[1][0].telegram_chat_id is None and calls[1][0].ntfy_url.endswith("private-topic")


def test_secondary_admin_cannot_inherit_deployment_owner_recipient():
    calls = []
    users = NS(get_by_uid=lambda uid: NS(extra={}, role="admin", email="another-admin@example.com"))
    push_review(7, 11, "CN", "2026-10-30", "private", users=users, factory=lambda **kwargs: calls.append(kwargs))
    assert not calls
