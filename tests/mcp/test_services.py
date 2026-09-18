"""Opt-in tests against disposable local services; never use a business database.

MCP_TEST_POSTGRES_ADMIN_URL must name an empty disposable database; these tests create
roles/tables. MCP_TEST_REDIS_ADMIN_URL must be a disposable Redis instance.
"""

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
            cursor.execute("GRANT USAGE ON SCHEMA public TO mcp_test_ro")
            cursor.execute("GRANT SELECT ON mcp_test_values TO mcp_test_ro")
    yield parsed.set(username="mcp_test_ro", password="test-only").render_as_string(hide_password=False)
    with psycopg2.connect(**parsed.translate_connect_args(username="user")) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE mcp_test_values")
            cursor.execute("DROP OWNED BY mcp_test_ro")
            cursor.execute("DROP ROLE mcp_test_ro")


def test_real_postgres_readonly_limits_and_timeout(postgres_url):
    reader = PostgresReader(postgres_url)
    assert reader.query("SHOW transaction_read_only")["rows"] == [["on"]]
    assert reader.query("SHOW statement_timeout")["rows"] == [["10s"]]
    assert reader.query("SHOW lock_timeout")["rows"] == [["2s"]]
    result = reader.query("SELECT * FROM mcp_test_values", max_rows=10)
    assert result["row_count"] == 10 and result["truncated"]
    assert reader.query("SELECT * FROM mcp_test_values")["row_count"] == 500
    assert reader.query("EXPLAIN SELECT * FROM mcp_test_values")["rows"]
    assert reader.query("SELECT string_agg('x', '') FROM generate_series(1, 3000000)")["truncated"]
    # Even bypassing the validator and transaction setting, grants prevent writes.
    with psycopg2.connect(**reader.url.translate_connect_args(username="user")) as conn:
        with conn.cursor() as cursor, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("DELETE FROM mcp_test_values")
    start = time.monotonic()
    with pytest.raises(psycopg2.errors.QueryCanceled):
        reader.query("SELECT count(*) FROM generate_series(1, 1000000000)")
    assert 8 <= time.monotonic() - start < 15


def test_real_redis_acl_and_response_limit():
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
    restricted_url = urlunsplit((parts.scheme, "mcp_test_ro:test-only@" + parts.netloc, parts.path, "", ""))
    reader = RedisReader(restricted_url)
    try:
        assert reader.read("GET", ["mcp:small"])["data"]["content"] == "hello"
        assert reader.read("GET", ["mcp:big"])["truncated"]
        assert reader.read("GET", ["mcp:small"])["data"]["content"] == "hello"
        assert reader.read("HGETALL", ["mcp:hash"])["data"]
        assert reader.read("SCAN", ["0"])["data"]
        with pytest.raises(ResponseError):
            reader.client.set("mcp:small", "forbidden")
    finally:
        reader.close()
        admin.delete("mcp:small", "mcp:big", "mcp:hash")
        admin.acl_deluser("mcp_test_ro")
        admin.close()
