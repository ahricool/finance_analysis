"""Google source lifecycle. No live Google calls."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError, OAuthState  # pragma: allowlist secret


class FakeRepo:
    def __init__(self, source):
        self.source = source

    def get_for_uid(self, uid):
        return self.source

    def get_or_create(self, uid):
        return self.source

    def get_by_id(self, source_id, *, uid):
        return self.source if self.source.id == source_id else None

    def save(self, source_id, *, uid, **changes):
        for key, value in changes.items():
            setattr(self.source, key, value)
        return self.source

    def update_health(self, *, source_id, uid, **changes):
        return self.save(source_id, uid=uid, **changes)

    def publish_generation(self, **kwargs):
        return self.source


def _source(**overrides):
    payload = dict(
        id=1,
        uid=1,
        spreadsheet_id="old-sheet",
        accounts_range="Accounts",
        positions_range="Positions",
        auth_status="CONNECTED",
        enabled=True,
        encrypted_credentials=b"blob",
        config_version=3,
        published_generation=4,
        content_hash="abc",
        published_snapshot={"uid": 1, "source_id": 1, "generation": 4, "content_hash": "abc"},
        risk_policy={"max_symbol_weight": 0.1, "vwap_mode": "exact_or_proxy"},
        policy_version=2,
        sync_status="OK",
        last_error_code=None,
    )
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.test/api/v1/holdings/oauth/callback")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_KEY", "a" * 44)
    from finance_analysis.integrations.google_sheets.config import reset_google_sheets_config  # pragma: allowlist secret

    reset_google_sheets_config()
    yield
    reset_google_sheets_config()


def test_reauth_does_not_disable_current_connection(google_env, monkeypatch):
    source = _source()
    oauth = MagicMock()
    oauth.create_state.return_value = "state"
    oauth.authorization_url.return_value = "https://accounts.google.com/o"
    service = HoldingsService(repository=FakeRepo(source), cache=MagicMock(), oauth=oauth)
    from finance_analysis.holdings import service as module  # pragma: allowlist secret

    monkeypatch.setattr(module, "parse_spreadsheet_id", lambda value: "old-sheet")
    monkeypatch.setattr(module, "validate_return_path", lambda value, config=None: "/market/holdings")
    monkeypatch.setattr(module, "new_code_verifier", lambda: "verifier")
    monkeypatch.setattr(module, "get_google_sheets_config", lambda: SimpleNamespace(configured=True, accounts_range="Accounts", positions_range="Positions", return_paths=["/market/holdings"]))
    result = service.connect(uid=1, spreadsheet_value="old-sheet", return_path="/market/holdings")
    assert source.enabled is True
    assert source.auth_status == "CONNECTED"
    assert result["auth_status"] == "CONNECTED"


def test_disconnect_persists_before_revoke_and_old_callback_cannot_reenable(google_env):
    source = _source()
    oauth = MagicMock()
    oauth.revoke.return_value = "revoked_or_already_invalid"
    cache = MagicMock()
    cache.clear_source.side_effect = RuntimeError("redis down")
    service = HoldingsService(repository=FakeRepo(source), cache=cache, oauth=oauth)
    result = service.disconnect(uid=1)
    assert result["auth_status"] == "DISCONNECTED"
    assert source.enabled is False
    assert source.auth_status == "DISCONNECTED"
    assert source.config_version == 4
    oauth.revoke.assert_called_once()
    oauth.consume_state.return_value = OAuthState(1, 1, 4, "/market/holdings", "v")
    with pytest.raises(GoogleOAuthError, match="断开"):
        service.callback(uid=1, code="code", state="state")
