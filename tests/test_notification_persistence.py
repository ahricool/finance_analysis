"""Real message persistence, external delivery separation, and API user scope."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models import Notification, User
from finance_analysis.database.repositories.notification import NotificationRepository
from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.endpoints import notifications
from finance_analysis.notification.config import NotificationConfig
from finance_analysis.notification.noise_control import reset_notification_noise_state
from finance_analysis.notification.service import NotificationService


class MessageDB:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        User.__table__.create(self.engine)
        Notification.__table__.create(self.engine)
        with self.get_session() as session, session.begin():
            session.add_all([User(id=i, username=str(i), email=f"{i}@example.test", role="user") for i in (1, 2)])

    @contextmanager
    def get_session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            yield session

    def _run_write_transaction(self, name, callback):
        with self.get_session() as session, session.begin():
            return callback(session)


@pytest.fixture
def repo():
    db = MessageDB()
    yield NotificationRepository(db)
    db.engine.dispose()


@pytest.fixture
def service(repo, monkeypatch):
    reset_notification_noise_state()
    config = NotificationConfig(telegram_bot_token="test", telegram_chat_id="1", ntfy_url="https://ntfy.sh/test")
    monkeypatch.setattr("finance_analysis.notification.service.get_notification_config", lambda: config)
    monkeypatch.setattr("finance_analysis.database.repositories.notification.NotificationRepository", lambda: repo)
    svc = NotificationService()
    svc._markdown_to_image_channels = set()
    svc.send_to_telegram = Mock(return_value=True)
    svc.send_to_ntfy = Mock(return_value=True)
    yield svc
    reset_notification_noise_state()


@pytest.mark.parametrize("mode", ["success", "no_channel", "failure", "suppressed", "push_disabled"])
def test_one_business_message_one_row_before_delivery(repo, service, mode):
    if mode == "no_channel":
        service._available_channels = []
    elif mode == "failure":
        service.send_to_telegram.side_effect = RuntimeError("offline")
        service.send_to_ntfy.return_value = False
    elif mode == "suppressed":
        service._config.notification_min_severity = "critical"

    def delivered(content):
        assert content == "Short push"
        assert repo.list_messages(uid=1)["total"] == 1
        return True

    if mode == "success":
        service.send_to_telegram.side_effect = delivered
        service.send_to_ntfy.side_effect = delivered
    result = service.send(
        "# Report\n\nFull content", push_content="Short push", uid=1, route_type="report", push=mode != "push_disabled"
    )
    assert result.notification_id is not None
    assert result.push_attempted is (mode in {"success", "failure"})
    assert result.push_sent is (mode == "success")
    rows = repo.list_messages(uid=1)["items"]
    assert len(rows) == 1 and rows[0]["title"] == "Report"
    assert repo.get_message(rows[0]["id"], uid=1).content == "# Report\n\nFull content"
    assert set(Notification.__table__.columns.keys()) == {
        "id",
        "uid",
        "title",
        "content",
        "route_type",
        "severity",
        "created_at",
    }
    if mode in {"no_channel", "suppressed", "push_disabled"}:
        service.send_to_telegram.assert_not_called()
        service.send_to_ntfy.assert_not_called()


def test_persistence_failure_does_not_stop_delivery(repo, service, monkeypatch):
    monkeypatch.setattr(repo, "create", Mock(side_effect=RuntimeError("database unavailable")))
    result = service.send("still deliver", uid=1)
    assert result.notification_id is None
    assert result.push_attempted and result.push_sent
    service.send_to_telegram.assert_called_once()
    service.send_to_ntfy.assert_called_once()


def test_dedup_suppresses_push_only(repo, service):
    service._config.notification_dedup_ttl_seconds = 60
    assert service.send("same", uid=1).push_sent
    result = service.send("different persisted body", push_content="same", uid=1)
    assert result.notification_id is not None and not result.push_attempted and not result.push_sent
    assert repo.list_messages(uid=1)["total"] == 2
    service.send_to_telegram.assert_called_once()


def test_api_scope_filter_pagination_and_detail(repo):
    own = repo.create(uid=1, title="own", content="needle " + "x" * 1000, route_type="report", severity="info")
    other = repo.create(uid=2, title="other", content="private", route_type="report", severity="info")
    public = repo.create(uid=None, title="global", content="needle", route_type="alert", severity="warning")
    app = FastAPI()
    app.include_router(notifications.router, prefix="/api/v1/notifications")
    app.dependency_overrides[get_effective_uid] = lambda: 1
    app.dependency_overrides[notifications.get_notification_repository] = lambda: repo
    with TestClient(app) as client:
        result = client.get("/api/v1/notifications?uid=2").json()
        assert [x["id"] for x in result["items"]] == [public, own]
        assert result["total"] == 2
        assert len(result["items"][1]["content_preview"]) == 240
        assert client.get(f"/api/v1/notifications/{other}").status_code == 404
        assert client.get(f"/api/v1/notifications/{public}").status_code == 200
        detail = client.get(f"/api/v1/notifications/{own}").json()
        assert len(detail["content"]) > 1000 and "uid" not in detail
        assert detail["created_at"].endswith("Z")
        result = client.get(
            "/api/v1/notifications", params={"keyword": "needle", "route_type": "report", "severity": "info"}
        ).json()
        assert result["total"] == 1 and result["items"][0]["id"] == own
        assert client.get("/api/v1/notifications?page_size=101").status_code == 422
        assert client.get("/api/v1/notifications?start_time=2030-01-01&end_time=2020-01-01").status_code == 422
        assert client.get("/api/v1/notifications?start_time=2030-01-01").json()["total"] == 0
        assert client.get("/api/v1/notifications?keyword=%25").json()["total"] == 0
        result = client.get("/api/v1/notifications?page_size=1&page=2").json()
        assert result["items"][0]["id"] == own and result["total"] == 2
    assert {x["id"] for x in repo.list_messages(uid=2)["items"]} == {other, public}
    with pytest.raises(ValueError):
        repo.list_messages(uid=None)
