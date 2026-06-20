# -*- coding: utf-8 -*-
"""Bot-owned runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class BotConfig:
    bot_enabled: bool = True
    bot_command_prefix: str = "/"
    bot_rate_limit_requests: int = 10
    bot_rate_limit_window: int = 60
    bot_admin_users: list[str] | None = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.bot_admin_users is None:
            self.bot_admin_users = []


@lru_cache(maxsize=1)
def get_bot_config() -> BotConfig:
    return BotConfig()
