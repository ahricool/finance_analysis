# -*- coding: utf-8 -*-
"""Holdings domain configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_bool, env_int, env_str  # pragma: allowlist secret
from finance_analysis.integrations.google_sheets.config import get_google_sheets_config  # pragma: allowlist secret


@dataclass(frozen=True, slots=True)
class HoldingsConfig:
    enabled: bool
    schema_version: str
    nav_max_age_hours: int
    oauth_state_ttl_seconds: int
    snapshot_ttl_seconds: int
    redis_url: str | None

    @property
    def google_configured(self) -> bool:
        return get_google_sheets_config().configured


@lru_cache(maxsize=1)
def get_holdings_config() -> HoldingsConfig:
    from finance_analysis.database.config import get_database_config  # pragma: allowlist secret

    return HoldingsConfig(
        enabled=env_bool("HOLDINGS_ENABLED", True),
        schema_version=env_str("HOLDINGS_SCHEMA_VERSION", "v1") or "v1",
        nav_max_age_hours=env_int("HOLDINGS_NAV_MAX_AGE_HOURS", 36, minimum=1),
        oauth_state_ttl_seconds=env_int("HOLDINGS_OAUTH_STATE_TTL_SECONDS", 600, minimum=60, maximum=3600),
        snapshot_ttl_seconds=env_int("HOLDINGS_SNAPSHOT_TTL_SECONDS", 7 * 24 * 3600, minimum=3600),
        redis_url=env_str("REDIS_URL") or get_database_config().redis_url,
    )


def reset_holdings_config() -> None:
    get_holdings_config.cache_clear()
