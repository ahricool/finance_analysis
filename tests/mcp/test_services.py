"""Opt-in tests against disposable local services; never use a business database.

MCP_TEST_POSTGRES_ADMIN_URL must name an empty disposable database; these tests create
roles/tables. MCP_TEST_REDIS_ADMIN_URL must be a disposable Redis instance.
"""

import base64
import os
import time

import psycopg2
import pytest
from redis import Redis
from redis.exceptions import ResponseError

from finance_analysis.mcp.postgres import PostgresReader
from finance_analysis.mcp.redis import ALLOWED, RedisReader

pytestmark = pytest.mark.network


@pytest.fixture
def postgres_url():
    url = os.getenv("MCP_TEST_POSTGRES_ADMIN_URL")
    if not url:
        pytest.skip("Requires disposable MCP_TEST_POSTGRES_ADMIN_URL")
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    with psycopg2.connect(**parsed.translate_connect_args(username="user")) as conn:
        with conn.cursor() as cursor:
            cursor.execute("CREATE ROLE mcp_test_ro LOGIN PASSWORD 'test-only' NOSUPERUSER NOCREATEDB NOCREATEROLE")
            cursor.execute("CREATE TABLE mcp_test_values(value integer)")
            cursor.execute("INSERT INTO mcp_test_values SELECT generate_series(1, 6000)")
            cursor.execute(
                "CREATE FUNCTION public.mcp_test_echo(value integer) RETURNS integer " "LANGUAGE SQL AS 'SELECT $1'"
            )
            cursor.execute("GRANT USAGE ON SCHEMA public TO mcp_test_ro")
            cursor.execute("GRANT SELECT ON mcp_test_values TO mcp_test_ro")
    yield parsed.set(username="mcp_test_ro", password="test-only").render_as_string(hide_password=False)
    with psycopg2.connect(**parsed.translate_connect_args(username="user")) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DROP FUNCTION public.mcp_test_echo(integer)")
            cursor.execute("DROP TABLE mcp_test_values")
            cursor.execute("DROP OWNED BY mcp_test_ro")
            cursor.execute("DROP ROLE mcp_test_ro")


def test_real_postgres_readonly_limits_and_timeout(postgres_url, monkeypatch):
    reader = PostgresReader(postgres_url)
    assert reader.query("SHOW transaction_read_only")["rows"] == [["on"]]
    assert reader.query("SHOW statement_timeout")["rows"] == [["10s"]]
    assert reader.query("SHOW lock_timeout")["rows"] == [["2s"]]
    result = reader.query("SELECT * FROM mcp_test_values", max_rows=10)
    assert result["row_count"] == 10 and result["truncated"]
    assert reader.query("SELECT * FROM mcp_test_values")["row_count"] == 500
    assert reader.query("EXPLAIN SELECT * FROM mcp_test_values")["rows"]
    assert reader.query("SELECT string_agg('x', '') FROM generate_series(1, 3000000)")["truncated"]
    assert reader.query("SELECT public.mcp_test_echo(42)")["rows"] == [[42]]
    assert reader.query("SELECT regexp_replace('abc', 'b', 'x')")["rows"] == [["axc"]]
    assert reader.query("SELECT array_to_string(ARRAY[1,2,3], ',')")["rows"] == [["1,2,3"]]
    assert reader.query("SELECT jsonb_each('{\"a\":1}'::jsonb)")["rows"]
    assert reader.query("SELECT jsonb_pretty('{\"a\":1}'::jsonb)")["rows"]
    assert reader.query("SELECT to_jsonb(ARRAY[1,2])")["rows"] == [[[1, 2]]]
    binary = reader.query("SELECT decode('deadbeef', 'hex')")["rows"][0][0]
    assert binary["encoding"] == "base64"
    assert base64.b64decode(binary["content"]).hex() == "deadbeef"
    error = call_tool(
        monkeypatch,
        postgres_url,
        "redis://reader:password@localhost/0",
        "postgres_query",
        {"sql": "SELECT not_existing_column FROM not_existing_table"},
    )
    assert error["isError"] is True
    assert "does not exist" in error["content"][0]["text"]
    assert "postgres.py" in error["content"][0]["text"]
    # Even bypassing the validator and transaction setting, grants prevent writes.
    with psycopg2.connect(**reader.url.translate_connect_args(username="user")) as conn:
        with conn.cursor() as cursor, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("DELETE FROM mcp_test_values")
    start = time.monotonic()
    with pytest.raises(psycopg2.errors.QueryCanceled):
        reader.query("SELECT count(*) FROM generate_series(1, 1000000000)")
    assert 8 <= time.monotonic() - start < 15


def test_real_redis_acl_and_response_limit(monkeypatch):
    url = os.getenv("MCP_TEST_REDIS_ADMIN_URL")
    if not url:
        pytest.skip("Requires disposable MCP_TEST_REDIS_ADMIN_URL")
    from urllib.parse import urlsplit, urlunsplit

    admin = Redis.from_url(url)
    parts = urlsplit(url)
    admin.execute_command(
        "ACL",
        "SETUSER",
        "mcp_test_ro",
        "reset",
        "on",
        ">test-only",
        "~*",
        "-@all",
        *["+" + cmd.lower() for cmd in ALLOWED],
        "+ping",
        "+select",
    )
    admin.set("mcp:small", "hello")
    admin.set("mcp:big", b"x" * (3 * 1024 * 1024))
    admin.hset("mcp:hash", mapping={"one": "1", "two": "2"})
    admin.sadd("mcp:set", "one", "two")
    admin.rpush("mcp:list", "one", "two")
    admin.zadd("mcp:zset", {"one": 1, "two": 2})
    admin.xadd("mcp:stream", {"field": "value"})
    restricted_url = urlunsplit((parts.scheme, "mcp_test_ro:test-only@" + parts.netloc, parts.path, "", ""))
    reader = RedisReader(restricted_url)
    try:
        assert reader.read("GET", ["mcp:small"])["data"]["content"] == "hello"
        assert reader.read("GET", ["mcp:big"])["truncated"]
        assert reader.read("GET", ["mcp:small"])["data"]["content"] == "hello"
        assert reader.read("HGETALL", ["mcp:hash"])["data"]
        assert reader.read("SCAN", ["0"])["data"]
        assert len(reader.read("LRANGE", ["mcp:list", "0", "-1"])["data"]) == 2
        assert len(reader.read("ZRANGE", ["mcp:zset", "-inf", "+inf", "BYSCORE", "WITHSCORES"])["data"]) == 4
        assert reader.read("XRANGE", ["mcp:stream", "-", "+"])["data"]
        assert reader.read("PING", [])["data"]["content"] == "PONG"
        assert reader.read("STRLEN", ["mcp:small"])["data"] == 5
        assert reader.read("GETRANGE", ["mcp:small", "0", "1"])["data"]["content"] == "he"
        assert reader.read("HEXISTS", ["mcp:hash", "one"])["data"] == 1
        assert len(reader.read("HKEYS", ["mcp:hash"])["data"]) == 2
        assert len(reader.read("HVALS", ["mcp:hash"])["data"]) == 2
        assert reader.read("SISMEMBER", ["mcp:set", "one"])["data"] == 1
        assert reader.read("SMISMEMBER", ["mcp:set", "one", "missing"])["data"] == [1, 0]
        assert reader.read("ZSCORE", ["mcp:zset", "one"])["data"]["content"] == "1"
        assert len(reader.read("ZMSCORE", ["mcp:zset", "one", "two"])["data"]) == 2
        assert reader.read("ZRANK", ["mcp:zset", "one"])["data"] == 0
        assert reader.read("ZREVRANK", ["mcp:zset", "one"])["data"] == 1
        assert reader.read("ZCOUNT", ["mcp:zset", "-inf", "+inf"])["data"] == 2
        assert reader.read("ZLEXCOUNT", ["mcp:zset", "-", "+"])["data"] == 2
        assert reader.read("DBSIZE", [])["data"] >= 7
        assert len(reader.read("TIME", [])["data"]) == 2
        assert reader.read("XINFO", ["STREAM", "mcp:stream"])["data"]
        assert reader.read("OBJECT", ["ENCODING", "mcp:small"])["data"]
        assert reader.read("OBJECT", ["REFCOUNT", "mcp:small"])["data"] >= 1
        assert reader.read("OBJECT", ["IDLETIME", "mcp:small"])["data"] >= 0
        assert reader.read("OBJECT", ["HELP"])["data"]
        # FREQ requires LFU eviction; the native configuration error is expected here.
        with pytest.raises(ResponseError, match="LFU"):
            reader.read("OBJECT", ["FREQ", "mcp:small"])
        error = call_tool(
            monkeypatch,
            "postgresql://reader:password@localhost/test",
            restricted_url,
            "redis_read",
            {"command": "HGETALL", "args": ["mcp:small"]},
        )
        assert error["isError"] is True
        assert "WRONGTYPE" in error["content"][0]["text"]
        assert "redis.py" in error["content"][0]["text"]
        with pytest.raises(ResponseError):
            reader.client.set("mcp:small", "forbidden")
    finally:
        reader.close()
        admin.delete("mcp:small", "mcp:big", "mcp:hash", "mcp:list", "mcp:zset", "mcp:stream", "mcp:set")
        admin.acl_deluser("mcp_test_ro")
        admin.close()


def call_tool(monkeypatch, database_url, redis_url, tool, arguments):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.mcp.config import MCPConfig
    from finance_analysis.mcp.server import install_mcp

    key = "integration-test-" + "a" * 32
    monkeypatch.setattr(MCPConfig, "from_env", lambda: MCPConfig(True, key, database_url, redis_url))
    app = FastAPI()
    install_mcp(app)
    with TestClient(app) as client:
        response = client.post(
            "/mcp/",
            headers={"Authorization": "Bearer " + key, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
        )
    assert response.status_code == 200
    return response.json()["result"]
