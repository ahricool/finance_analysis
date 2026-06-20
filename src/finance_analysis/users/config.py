# -*- coding: utf-8 -*-
"""User/authentication configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_str


@dataclass
class AuthConfig:
    secret_key: str = ""


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    return AuthConfig(
        secret_key=env_str("SECRET_KEY", "") or "",
    )
