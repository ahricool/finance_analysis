# -*- coding: utf-8 -*-
"""Holdings source, OAuth, and snapshot publish service."""

from __future__ import annotations

from typing import Any

import redis

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.config import get_database_config  # pragma: allowlist secret
from finance_analysis.database.repositories.holdings import HoldingsRepository  # pragma: allowlist secret
from finance_analysis.holdings.cache import HoldingsCache  # pragma: allowlist secret
from finance_analysis.holdings.config import get_holdings_config  # pragma: allowlist secret
from finance_analysis.holdings.context import render_holdings_context  # pragma: allowlist secret
from finance_analysis.holdings.models import HoldingsSnapshot  # pragma: allowlist secret
from finance_analysis.holdings.snapshot import SnapshotRejected, build_snapshot  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.client import GoogleSheetsClient, GoogleSheetsError  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.config import get_google_sheets_config  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.credentials import decrypt_credentials  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.oauth import (  # pragma: allowlist secret
    GoogleOAuthError,
    GoogleOAuthService,
    GoogleTokens,
    OAuthState,
    new_code_verifier,
    validate_return_path,
)
from finance_analysis.integrations.google_sheets.spreadsheet import parse_spreadsheet_id  # pragma: allowlist secret


def redis_client(url: str | None = None):
    return redis.Redis.from_url(url or get_database_config().redis_url, decode_responses=True)


class HoldingsService:
    def __init__(
        self,
        repository: HoldingsRepository | None = None,
        cache: HoldingsCache | None = None,
        oauth: GoogleOAuthService | None = None,
        sheets_factory=None,
        redis_client_obj=None,
    ) -> None:
        client = redis_client_obj or redis_client()
        self.repository = repository or HoldingsRepository()
        self.cache = cache or HoldingsCache(client)
        self.oauth = oauth or GoogleOAuthService(client)
        self.sheets_factory = sheets_factory or (
            lambda credentials: GoogleSheetsClient(credentials)
        )

    def public_source(self, uid: int) -> dict[str, Any]:
        google = get_google_sheets_config()
        config = get_holdings_config()
        source = self.repository.get_for_uid(uid)
        if not google.configured:
            auth_status = "NOT_CONFIGURED"
        elif source is None:
            auth_status = "DISCONNECTED"
        else:
            auth_status = source.auth_status
        return {
            "google_configured": google.configured,
            "holdings_enabled": config.enabled,
            "missing_config": list(google.missing),
            "source_id": None if source is None else source.id,
            "spreadsheet_id": None if source is None else source.spreadsheet_id,
            "schema_version": None if source is None else source.schema_version,
            "auth_status": auth_status,
            "sync_status": None if source is None else source.sync_status,
            "enabled": False if source is None else source.enabled,
            "last_attempt_at": None if source is None else source.last_attempt_at,
            "last_success_at": None if source is None else source.last_success_at,
            "last_error_code": None if source is None else source.last_error_code,
            "published_generation": 0 if source is None else source.published_generation,
            "content_hash": None if source is None else source.content_hash,
            "config_version": 1 if source is None else source.config_version,
            "policy_version": 1 if source is None else source.policy_version,
            "can_background_sync": bool(
                source is not None
                and source.enabled
                and source.auth_status == "CONNECTED"
                and source.encrypted_credentials
            ),
        }

    def connect(self, *, uid: int, spreadsheet_value: str, return_path: str | None) -> dict[str, Any]:
        google = get_google_sheets_config()
        if not google.configured:
            raise GoogleOAuthError("not_configured", "Google OAuth 未配置")
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_value)
        path = validate_return_path(return_path, config=google)
        source = self.repository.get_or_create(uid)
        changes: dict[str, Any] = {
            "spreadsheet_id": spreadsheet_id,
            "accounts_range": google.accounts_range,
            "positions_range": google.positions_range,
            "auth_status": "PENDING",
            "enabled": False,
        }
        if source.spreadsheet_id != spreadsheet_id:
            changes["config_version"] = int(source.config_version) + 1
        source = self.repository.save(source.id, uid=uid, **changes)
        verifier = new_code_verifier()
        state = self.oauth.create_state(
            OAuthState(
                uid=uid,
                source_id=source.id,
                config_version=source.config_version,
                return_path=path,
                code_verifier=verifier,
            )
        )
        return {
            "authorization_url": self.oauth.authorization_url(state=state, code_verifier=verifier),
            "return_path": path,
            "auth_status": "PENDING",
        }

    def callback(self, *, uid: int, code: str, state: str) -> dict[str, Any]:
        payload = self.oauth.consume_state(state)
        if payload.uid != uid:
            raise GoogleOAuthError("user_mismatch", "登录用户与授权流程不一致，请重新连接")
        source = self.repository.get_by_id(payload.source_id, uid=uid)
        if source is None or source.config_version != payload.config_version:
            raise GoogleOAuthError("config_changed", "持仓来源配置已变化，请重新连接")
        tokens = self.oauth.exchange_code(code=code, code_verifier=payload.code_verifier)
        previous = decrypt_credentials(source.encrypted_credentials) if source.encrypted_credentials else {}
        if not tokens.has_offline_access:
            if previous.get("refresh_token") and source.auth_status == "CONNECTED":
                return {
                    "return_path": payload.return_path,
                    "auth_status": source.auth_status,
                    "offline_granted": False,
                    "replaced": False,
                }
            self.repository.save(
                source.id,
                uid=uid,
                auth_status="CONNECTED_NO_OFFLINE",
                enabled=False,
                last_error_code="missing_refresh_token",
            )
            return {
                "return_path": payload.return_path,
                "auth_status": "CONNECTED_NO_OFFLINE",
                "offline_granted": False,
                "replaced": False,
            }
        blob = self.oauth.encrypt_tokens(tokens, previous=previous)
        self.repository.save(
            source.id,
            uid=uid,
            encrypted_credentials=blob,
            auth_status="CONNECTED",
            enabled=True,
            last_error_code=None,
            sync_status="IDLE",
        )
        return {
            "return_path": payload.return_path,
            "auth_status": "CONNECTED",
            "offline_granted": True,
            "replaced": True,
        }

    def disconnect(self, *, uid: int) -> dict[str, Any]:
        source = self.repository.get_for_uid(uid)
        if source is None:
            return {"auth_status": "DISCONNECTED", "google_revoke": "skipped_no_source"}
        revoke = "skipped_no_token"
        try:
            revoke = self.oauth.revoke(source.encrypted_credentials)
        except Exception:
            revoke = "revoke_request_failed"
        self.cache.clear_source(uid, source.id, source.published_generation)
        self.repository.save(
            source.id,
            uid=uid,
            encrypted_credentials=None,
            auth_status="DISCONNECTED",
            enabled=False,
            sync_status="IDLE",
            last_error_code=None,
        )
        return {"auth_status": "DISCONNECTED", "google_revoke": revoke}

    def get_snapshot(self, *, uid: int) -> HoldingsSnapshot | None:
        source = self.repository.get_for_uid(uid)
        if source is None or source.published_generation <= 0:
            return None
        cached = self.cache.get_snapshot(uid, source.id, source.published_generation)
        if cached is not None:
            return cached
        if source.content_hash:
            rebuilt = self.sync(uid=uid, force=True)
            return rebuilt.get("snapshot")
        return None

    def get_context(self, *, uid: int) -> str | None:
        snapshot = self.get_snapshot(uid=uid)
        if snapshot is None:
            return None
        cached = self.cache.get_context(uid, snapshot.source_id, snapshot.content_hash)
        return cached or render_holdings_context(snapshot)

    def sync(self, *, uid: int, force: bool = False) -> dict[str, Any]:
        source = self.repository.get_for_uid(uid)
        if source is None:
            raise GoogleOAuthError("not_connected", "尚未连接 Google Sheet")
        self.repository.update_health(source_id=source.id, uid=uid, last_attempt_at=utc_now(), sync_status="SYNCING")
        try:
            credentials = self.oauth.credentials_from_blob(source.encrypted_credentials)
            if credentials is None:
                raise GoogleOAuthError("needs_reauth", "缺少可用的离线凭据")
            client = self.sheets_factory(credentials)
            batch = client.fetch_batch(
                source.spreadsheet_id,
                {"Accounts": source.accounts_range, "Positions": source.positions_range},
            )
        except GoogleOAuthError as exc:
            status = "NEEDS_REAUTH" if exc.code == "needs_reauth" else source.auth_status
            self.repository.update_health(
                source_id=source.id,
                uid=uid,
                auth_status=status,
                sync_status="UNAVAILABLE",
                last_error_code=exc.code,
                enabled=False if exc.code == "needs_reauth" else source.enabled,
            )
            raise
        except GoogleSheetsError as exc:
            self.repository.update_health(
                source_id=source.id,
                uid=uid,
                sync_status="UNAVAILABLE",
                last_error_code=exc.code,
            )
            raise

        previous = self.cache.get_snapshot(uid, source.id, source.published_generation)
        try:
            snapshot = build_snapshot(
                uid=uid,
                source_id=source.id,
                batch=batch,
                generation=source.published_generation + 1,
                previous=previous,
            )
        except SnapshotRejected as exc:
            self.repository.update_health(
                source_id=source.id,
                uid=uid,
                sync_status="REJECTED",
                last_error_code=exc.code,
            )
            raise

        same_hash = source.content_hash == snapshot.content_hash
        if same_hash and not force:
            snapshot = snapshot.model_copy(update={"generation": source.published_generation})
            cached = self.cache.get_snapshot(uid, source.id, source.published_generation)
            if cached is None:
                self.cache.write_snapshot(snapshot, context_text=render_holdings_context(snapshot))
            self.repository.update_health(
                source_id=source.id,
                uid=uid,
                sync_status="OK",
                last_success_at=utc_now(),
                last_error_code=None,
            )
            return {"changed": False, "snapshot": snapshot, "generation": source.published_generation}

        if same_hash and force:
            snapshot = snapshot.model_copy(update={"generation": source.published_generation})
            self.cache.write_snapshot(snapshot, context_text=render_holdings_context(snapshot))
            self.repository.update_health(
                source_id=source.id,
                uid=uid,
                sync_status="OK",
                last_success_at=utc_now(),
                last_error_code=None,
            )
            return {"changed": False, "snapshot": snapshot, "generation": source.published_generation, "cache_rebuilt": True}

        published = self.repository.publish_generation(
            source_id=source.id,
            uid=uid,
            expected_config_version=source.config_version,
            expected_generation=source.published_generation,
            new_generation=snapshot.generation,
            content_hash=snapshot.content_hash,
            sync_status="OK",
        )
        if published is None:
            raise SnapshotRejected("stale_generation", "同步结果已过期，未覆盖更新版本")
        self.cache.write_snapshot(snapshot, context_text=render_holdings_context(snapshot))
        return {"changed": True, "snapshot": snapshot, "generation": snapshot.generation}

    def update_policy(self, *, uid: int, policy: dict[str, Any]) -> dict[str, Any]:
        source = self.repository.get_or_create(uid)
        updated = self.repository.save(
            source.id,
            uid=uid,
            risk_policy=dict(policy),
            policy_version=int(source.policy_version) + 1,
        )
        return {"policy": updated.risk_policy, "policy_version": updated.policy_version}
