"""OAuth state, token encryption, and secret redaction. No live Google calls."""

from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from finance_analysis.core.secret_redact import redact_secrets  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.config import reset_google_sheets_config  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.credentials import decrypt_credentials, encrypt_credentials  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import GoogleOAuthError, GoogleOAuthService, OAuthState, new_code_verifier  # pragma: allowlist secret


@pytest.fixture
def token_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.test/api/v1/holdings/oauth/callback")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_KEY", key)
    reset_google_sheets_config()
    yield key
    reset_google_sheets_config()


def test_state_is_single_use(token_key):
    redis = MagicMock()
    redis.set.return_value = True
    redis.getdel.return_value = None
    redis.pipeline.return_value.execute.return_value = [
        '{"uid":1,"source_id":2,"config_version":1,"return_path":"/market/holdings","code_verifier":"abc"}',
        1,
    ]
    service = GoogleOAuthService(redis)
    state = service.create_state(
        OAuthState(uid=1, source_id=2, config_version=1, return_path="/market/holdings", code_verifier=new_code_verifier())
    )
    assert redis.set.call_args.kwargs["nx"] is True
    consumed = service.consume_state(state)
    assert consumed.uid == 1
    redis.pipeline.return_value.execute.return_value = [None, 0]
    with pytest.raises(GoogleOAuthError, match="state"):
        service.consume_state(state)


def test_refresh_token_roundtrip_and_redaction(token_key):
    blob = encrypt_credentials({"refresh_token": "rt-secret", "access_token": "at-secret", "client_id": "client"})
    decoded = decrypt_credentials(blob)
    assert decoded["refresh_token"] == "rt-secret"
    text = redact_secrets("callback?code=abc123&state=xyz /api/v1/holdings/oauth/callback?code=abc123")
    assert "abc123" not in text
    assert "[REDACTED]" in text
    assert "refresh_token" in redact_secrets('{"refresh_token":"rt-secret"}')
    assert "rt-secret" not in redact_secrets('{"refresh_token":"rt-secret"}')
