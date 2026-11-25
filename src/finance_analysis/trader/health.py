"""Container health check: same-host Trader heartbeat and active lease."""
import socket

from finance_analysis.integrations.market_data.realtime_state import keys


def healthy(redis, hostname):
    status = redis.hgetall(keys.TRADER_HEARTBEAT_KEY)
    return (
        status.get("status") == "READY"
        and status.get("instance_id", "").split(":", 1)[0] == hostname
        and bool(status.get("lease_token"))
        and redis.get(keys.TRADER_LEADER_LOCK_KEY) == status["lease_token"]
        and redis.ttl(keys.TRADER_HEARTBEAT_KEY) > 0
    )


def main():
    from redis import Redis
    from finance_analysis.config import load_env
    from finance_analysis.market_stream.config import MarketStreamConfig

    load_env()
    try:
        with Redis.from_url(MarketStreamConfig.from_env().redis_url, decode_responses=True,
                            socket_connect_timeout=2, socket_timeout=2) as redis:
            return 0 if healthy(redis, socket.gethostname()) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
