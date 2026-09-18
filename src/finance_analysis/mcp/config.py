"""MCP configuration using the application's existing environment loader."""

from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

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
            env_str("MCP_DATABASE_URL", ""),
            env_str("MCP_REDIS_URL", ""),
        )
        if not config.enabled:
            return config
        if len(config.api_key) < 32 or not all(33 <= ord(char) <= 126 for char in config.api_key):
            raise ValueError("MCP_API_KEY must contain at least 32 ASCII characters")
        try:
            db = make_url(config.database_url)
            redis = urlsplit(config.redis_url)
            business_db = env_str("DATABASE_URL", "")
            business_redis = urlsplit(env_str("REDIS_URL", ""))
            valid = (
                db.drivername in {"postgresql", "postgresql+psycopg2"}
                and db.username
                and db.password
                and not (set(db.query) - {"sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl"})
                and redis.scheme in {"redis", "rediss"}
                and redis.username
                and unquote(redis.username) != "default"
                and not redis.query
                and not redis.fragment
                and redis.password
            )
            if business_db and db.username == make_url(business_db).username:
                valid = False
            if unquote(redis.username or "") == unquote(business_redis.username or ""):
                valid = False
            if not valid:
                raise ValueError()
        except Exception:
            raise ValueError("MCP requires separate PostgreSQL and named Redis ACL credentials") from None
        return config
