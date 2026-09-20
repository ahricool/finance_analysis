"""MCP configuration using the application's existing environment loader."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from finance_analysis.config import env_bool, env_str, load_env


@dataclass(frozen=True)
class MCPConfig:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    database_url: str = field(default="", repr=False)
    redis_url: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        load_env()
        config = cls(
            env_bool("MCP_ENABLED", False),
            env_str("MCP_API_KEY", ""),
            env_str("MCP_DATABASE_URL", "").strip() or env_str("DATABASE_URL", "").strip(),
            env_str("MCP_REDIS_URL", "").strip() or env_str("REDIS_URL", "").strip(),
        )
        if not config.enabled:
            return config
        if len(config.api_key) < 32 or not all(33 <= ord(char) <= 126 for char in config.api_key):
            raise ValueError("MCP_API_KEY must contain at least 32 ASCII characters")
        try:
            db = make_url(config.database_url)
            if (
                db.drivername not in {"postgresql", "postgresql+psycopg2"}
                or set(db.query) - {"sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl"}
            ):
                raise ValueError()
        except Exception:
            raise ValueError("MCP requires a valid PostgreSQL URL: set MCP_DATABASE_URL or DATABASE_URL") from None
        try:
            redis = urlsplit(config.redis_url)
            if (
                redis.scheme not in {"redis", "rediss"}
                or not redis.hostname
                or redis.query
                or redis.fragment
                or (redis.port is not None and not 1 <= redis.port <= 65535)
            ):
                raise ValueError()
        except Exception:
            raise ValueError("MCP requires a valid Redis URL: set MCP_REDIS_URL or REDIS_URL") from None
        return config
