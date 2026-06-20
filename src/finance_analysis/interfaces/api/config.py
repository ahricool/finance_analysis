# -*- coding: utf-8 -*-
"""API server configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class ApiServerConfig:
    webui_host: str = "0.0.0.0"
    webui_port: int = 8000


@lru_cache(maxsize=1)
def get_api_server_config() -> ApiServerConfig:
    return ApiServerConfig()
