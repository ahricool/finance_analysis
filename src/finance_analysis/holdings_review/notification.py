"""Deliver private reviews only to their owner's configured recipients."""

from dataclasses import replace
import hashlib

from finance_analysis.database.repositories.user import UserRepository, normalize_user_extra, DEFAULT_ADMIN_EMAIL
from finance_analysis.notification.config import get_notification_config
from finance_analysis.notification.service import NotificationService


def push_review(uid, notification_id, market, day, markdown, *, users=None, factory=NotificationService):
    user = (users or UserRepository()).get_by_uid(uid)
    if user is None:
        return
    profile = normalize_user_extra(user.extra)["notification"]
    base = get_notification_config()
    targets = []
    for item in profile["telegram"]:
        if item.get("bot_token") and item.get("chat_id"):
            targets.append(
                replace(
                    base,
                    telegram_bot_token=item["bot_token"],
                    telegram_chat_id=item["chat_id"],
                    telegram_message_thread_id=None,
                    ntfy_url=None,
                    ntfy_token=None,
                )
            )
    for item in profile["ntfy"]:
        if item.get("url"):
            targets.append(
                replace(base, ntfy_url=item["url"], ntfy_token=None, telegram_bot_token=None, telegram_chat_id=None)
            )
    # The deployment-wide destination belongs to the administrator, never to every tenant.
    if not targets and user.role == "admin" and getattr(user, "email", "").lower() == DEFAULT_ADMIN_EMAIL.lower():
        targets = [base]
    seen = set()
    for config in targets:
        recipient = f"{config.telegram_bot_token}:{config.telegram_chat_id}:{config.ntfy_url}"
        digest = hashlib.sha256(recipient.encode()).hexdigest()[:16]
        if digest in seen:
            continue
        seen.add(digest)
        factory(config=config).push_existing(
            markdown,
            notification_id=notification_id,
            route_type="report",
            dedup_key=f"holdings-review:{uid}:{market}:{day}:{digest}",
        )
