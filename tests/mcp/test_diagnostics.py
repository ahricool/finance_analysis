"""Offline security and protocol regression coverage for administrator diagnostics."""

import io
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from finance_analysis.mcp.config import MCPConfig
from finance_analysis.mcp.filesystem import FileReader
from finance_analysis.mcp.postgres import PostgresReader
from finance_analysis.mcp.redis import BoundedBuffer, ResponseTooLarge, validate_command, ALLOWED
from finance_analysis.mcp.security import validate_sql
from finance_analysis.mcp.server import install_mcp

KEY = "test-key-" + "a" * 32


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT * FROM xxx LIMIT 10",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW timezone",
        "EXPLAIN SELECT 1",
        "SELECT '; DELETE'",
        "SELECT count(*) FROM x",
        "SELECT 1 /* DELETE */;",
        "SELECT lower('ABC')",
        "SELECT regexp_replace('abc', 'b', 'x')",
        "SELECT jsonb_each('{\"a\":1}'::jsonb)",
        "SELECT jsonb_pretty('{\"a\":1}'::jsonb)",
        "SELECT array_to_string(ARRAY[1,2,3], ',')",
        "SELECT to_jsonb(ARRAY[1,2])",
        "SELECT decode('deadbeef', 'hex')",
        "SELECT reporting.existing_function(1)",
    ],
)
def test_sql_allowed(sql):
    validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM x",
        "UPDATE x SET a=1",
        "INSERT INTO x VALUES(1)",
        "DROP TABLE x",
        "CREATE TABLE x(a int)",
        "TRUNCATE x",
        "SELECT 1 INTO x",
        "EXPLAIN ANALYZE SELECT 1",
        "EXPLAIN (ANALYZE false) SELECT 1",
        "SELECT 1; DELETE FROM x",
        "WITH x AS (DELETE FROM y RETURNING *) SELECT * FROM x",
        "SELECT * FROM x FOR UPDATE",
        "SELECT * FROM x FOR SHARE",
        "COPY x TO PROGRAM 'id'",
        "CALL x()",
        "DO 'BEGIN END'",
        "SELECT set_config('a','b',false)",
        "SELECT pg_advisory_lock(1)",
        "EXPLAIN DELETE FROM x",
        "",
        "SELECT pg_catalog.pg_read_file('/etc/passwd')",
    ],
)
def test_sql_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


@pytest.mark.parametrize(
    "command", ["SET", "DEL", "KEYS", "EVAL", "CONFIG", "FLUSHALL", "CLIENT", "DEBUG", "GET\r\nSET"]
)
def test_redis_rejected(command):
    with pytest.raises(ValueError):
        validate_command(command, [])


@pytest.mark.parametrize("command", sorted(ALLOWED))
def test_redis_allowed(command):
    args = ["k", "0", "10"] if command in {"LRANGE", "ZRANGE", "ZREVRANGE"} else []
    if command in {"XRANGE", "XREVRANGE"}:
        args = ["k", "-", "+"]
    assert validate_command(command, args)[0] == command


def test_redis_response_bound():
    buffer = BoundedBuffer(io.BytesIO())
    with pytest.raises(ResponseTooLarge):
        buffer.read(3 * 1024 * 1024)


@pytest.fixture
def files(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/worker.log").write_text("one\ntwo\nthree\n")
    return FileReader(tmp_path)


def test_files(files):
    assert files.list("/")["entries"][0]["filename"] == "logs"
    assert files.stat("logs/worker.log")["type"] == "file"
    assert files.read("logs/worker.log", 4, 3)["content"] == "two"
    assert files.read("logs/worker.log", 4, 3)["truncated"]
    assert files.tail("logs/worker.log", 2)["content"] == "two\nthree\n"
    assert files.read("logs/worker.log", 999)["content"] == ""
    for kwargs in [{"max_bytes": 2**30}, {"offset": -1}]:
        with pytest.raises(ValueError):
            files.read("logs/worker.log", **kwargs)


@pytest.mark.parametrize("path", ["../../etc/passwd", "/data/../etc/passwd", "../", "logs/../../etc"])
def test_traversal(files, path):
    with pytest.raises(ValueError):
        files.read(path)


def test_symlinks(files):
    (files.root / "escape").symlink_to("/etc/passwd")
    (files.root / "dir").symlink_to("/etc")
    for path in ["escape", "dir/passwd"]:
        with pytest.raises((ValueError, OSError)):
            files.read(path)
    # Even in-jail symlinks are denied, avoiding a resolve/open race.
    (files.root / "inside").symlink_to(files.root / "logs/worker.log")
    with pytest.raises(OSError):
        files.read("inside")


@pytest.fixture
def client(monkeypatch, files):
    monkeypatch.setattr(
        MCPConfig,
        "from_env",
        lambda: MCPConfig(
            True, KEY, "postgresql://reader:password@localhost/test", "redis://reader:password@localhost/0"
        ),
    )
    monkeypatch.setattr("finance_analysis.mcp.filesystem.FileReader", lambda: files)
    app = FastAPI()
    install_mcp(app)
    with TestClient(app) as client:
        yield client


def test_auth_and_download(client):
    for path in ["/mcp", "/mcp/", "/mcp/files/logs/worker.log"]:
        for headers in [{}, {"Authorization": "Bearer wrong"}]:
            assert client.get(path, headers=headers).status_code == 401
    headers = {"Authorization": "Bearer " + KEY}
    assert client.get("/mcp/files/logs/worker.log", headers=headers).content == b"one\ntwo\nthree\n"
    response = client.get("/mcp/files/logs/worker.log", headers={**headers, "Range": "bytes=4-6"})
    assert response.status_code == 206 and response.content == b"two"
    assert client.get("/mcp/files/logs/worker.log", headers={**headers, "Range": "bytes=999-"}).status_code == 416
    assert client.get("/mcp/files/%2e%2e/etc/passwd", headers=headers).status_code == 404


def rpc(client, method, params=None):
    return client.post(
        "/mcp/",
        headers={"Authorization": "Bearer " + KEY, "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_mcp_protocol(client):
    response = rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )
    assert response.status_code == 200
    assert "serverInfo" in response.json()["result"]
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "postgres_query",
        "redis_read",
        "fs_list",
        "fs_stat",
        "fs_read",
        "fs_tail",
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    result = rpc(client, "tools/call", {"name": "fs_read", "arguments": {"path": "logs/worker.log"}})
    assert json.loads(result.json()["result"]["content"][0]["text"])["content"] == "one\ntwo\nthree\n"


def test_disabled(monkeypatch):
    monkeypatch.setattr(MCPConfig, "from_env", lambda: MCPConfig())
    app = FastAPI()
    install_mcp(app)
    with TestClient(app) as client:
        assert client.post("/mcp/").status_code == 404
        assert client.get("/mcp/files/a").status_code == 404


def test_postgres_limits(monkeypatch):
    calls = {}

    class Cursor:
        description = [SimpleNamespace(name="number")]

        def __enter__(self):
            self.rows = iter([[1], [2], [3]])
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql):
            calls.setdefault("sql", []).append(sql)

        def fetchone(self):
            return [False] * 5

        def fetchmany(self, size):
            row = next(self.rows, None)
            return [row] if row else []

    class Connection:
        def cancel(self):
            pass

        def cursor(self, **kwargs):
            return Cursor()

        def set_session(self, **kwargs):
            calls["session"] = kwargs

        def rollback(self):
            calls["rollback"] = True

        def close(self):
            calls["closed"] = True

    def connect(**kwargs):
        calls["connect"] = kwargs
        return Connection()

    monkeypatch.setattr("finance_analysis.mcp.postgres.psycopg2.connect", connect)
    reader = PostgresReader("postgresql://reader:password@localhost/test")
    result = reader.query("SELECT 1", 2)
    assert result["row_count"] == 2 and result["truncated"]
    assert "SELECT 1" in calls["sql"]
    assert calls["session"]["readonly"]
    assert "statement_timeout=10000" in calls["connect"]["options"]
    assert "lock_timeout=2000" in calls["connect"]["options"]
    assert calls["closed"] and calls["rollback"]
    with pytest.raises(ValueError):
        reader.query("SELECT 1", 5001)
    monkeypatch.setattr("finance_analysis.mcp.postgres.MAX_RESULT_BYTES", 260)
    assert reader.query("SELECT 1")["truncated"]


def test_config_fails_closed(monkeypatch):
    monkeypatch.setattr("finance_analysis.mcp.config.load_env", lambda: None)
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_API_KEY", KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://business:pw@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    monkeypatch.setenv("MCP_DATABASE_URL", "postgresql://reader:pw@localhost/test")
    monkeypatch.setenv("MCP_REDIS_URL", "redis://reader:pw@localhost/0")
    assert MCPConfig.from_env().enabled
    monkeypatch.setenv("MCP_DATABASE_URL", "postgresql://business:pw@localhost/test")
    with pytest.raises(ValueError):
        MCPConfig.from_env()
    monkeypatch.setenv("MCP_DATABASE_URL", "postgresql://reader:pw@localhost/test")
    monkeypatch.setenv("MCP_REDIS_URL", "redis://default:pw@localhost/0")
    with pytest.raises(ValueError):
        MCPConfig.from_env()
    monkeypatch.setenv("MCP_ENABLED", "false")
    assert not MCPConfig.from_env().enabled


def test_existing_api_auth_is_unchanged(monkeypatch):
    monkeypatch.setattr(MCPConfig, "from_env", lambda: MCPConfig())
    from finance_analysis.interfaces.api.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/status").status_code == 200
        assert client.get("/api/v1/watch-list").status_code == 401
        assert client.post("/mcp/").status_code == 404


def test_audit_does_not_log_key_or_content(client, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        rpc(client, "tools/call", {"name": "fs_read", "arguments": {"path": "logs/worker.log"}})
    assert "tool=fs_read" in caplog.text
    assert KEY not in caplog.text and "one\\ntwo" not in caplog.text


def test_download_suffix_and_invalid_ranges(client):
    headers = {"Authorization": "Bearer " + KEY}
    response = client.get("/mcp/files/logs/worker.log", headers={**headers, "Range": "bytes=-6"})
    assert response.status_code == 206 and response.content == b"three\n"
    for value in ["bytes=1-2,4-5", "bytes=-0", "bytes=6-2"]:
        assert client.get("/mcp/files/logs/worker.log", headers={**headers, "Range": value}).status_code == 416


def test_download_symlink_denied(client, files):
    (files.root / "escape").symlink_to("/etc/passwd")
    assert client.get("/mcp/files/escape", headers={"Authorization": "Bearer " + KEY}).status_code == 404


def test_tail_byte_window_and_binary(files):
    (files.root / "large").write_bytes(b"a" * (2 * 1024 * 1024))
    result = files.tail("large")
    assert result["truncated"] and result["line_count"] == 0
    (files.root / "binary").write_bytes(b"\xff\xfe")
    assert files.read("binary")["encoding"] == "base64"


@pytest.mark.parametrize(
    "database_url,redis_url",
    [
        ("postgresql://reader:pw@localhost/test?user=business", "redis://reader:pw@localhost/0"),
        ("postgresql://reader:pw@localhost/test", "redis://%64efault:pw@localhost/0"),
        ("postgresql://reader:pw@localhost/test", "redis://reader:pw@localhost/0?username=default"),
        ("postgresql://reader:pw@localhost/test", "redis://reader:pw@localhost/0?socket_timeout=9999"),
    ],
)
def test_connection_query_options_cannot_override_security(monkeypatch, database_url, redis_url):
    monkeypatch.setattr("finance_analysis.mcp.config.load_env", lambda: None)
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_API_KEY", KEY)
    monkeypatch.setenv("MCP_DATABASE_URL", database_url)
    monkeypatch.setenv("MCP_REDIS_URL", redis_url)
    with pytest.raises(ValueError):
        MCPConfig.from_env()


@pytest.mark.parametrize(
    "command,args",
    [
        ("LRANGE", ["k", "0", "-1"]),
        ("ZRANGE", ["k", "-inf", "+inf", "BYSCORE", "LIMIT", "0", "10000", "WITHSCORES"]),
        ("ZRANGE", ["k", "-", "+", "BYLEX"]),
        ("ZREVRANGE", ["k", "0", "-1", "WITHSCORES"]),
        ("XRANGE", ["k", "-", "+"]),
        ("XRANGE", ["k", "-", "+", "COUNT", "99999"]),
        ("SCAN", ["0", "COUNT", "99999"]),
    ],
)
def test_redis_native_arguments_unchanged(command, args):
    assert validate_command(command, args) == (command, args)


@pytest.mark.parametrize(
    "command,args",
    [
        ("SCAN", ["0"]),
        ("HSCAN", ["key", "0"]),
        ("SCAN", ["0", "MATCH", "COUNT"]),
        ("ZSCAN", ["key", "0", "MATCH", "*"]),
    ],
)
def test_scan_default_count(command, args):
    assert validate_command(command, args)[1] == args + ["COUNT", "500"]


@pytest.mark.parametrize("value", [bytes.fromhex("deadbeef"), bytearray(b"abc"), memoryview(b"abc")])
def test_binary_json_is_recoverable(value):
    import base64
    from finance_analysis.mcp.serialization import encoded

    result = json.loads(encoded(value))
    assert result["encoding"] == "base64"
    assert base64.b64decode(result["content"]) == bytes(value)


def test_common_postgres_types_are_stable():
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from uuid import UUID
    from finance_analysis.mcp.serialization import encoded

    values = [date(2026, 9, 18), datetime(2026, 9, 18, tzinfo=timezone.utc), Decimal("123.4500"), UUID(int=1)]
    assert json.loads(encoded(values)) == [str(value) for value in values]


@pytest.mark.parametrize(
    "tool,arguments,message",
    [
        ("postgres_query", {"sql": "DELETE FROM x"}, "Only SELECT"),
        ("postgres_query", {"sql": "SELECT 1", "max_rows": 5001}, "max_rows"),
        ("redis_read", {"command": "SET", "args": ["a", "b"]}, "Redis command SET is not allowed"),
        ("fs_read", {"path": "../etc/passwd"}, "Invalid data path"),
    ],
)
def test_validation_is_mcp_tool_error(client, tool, arguments, message):
    response = rpc(client, "tools/call", {"name": tool, "arguments": arguments})
    result = response.json()["result"]
    assert result["isError"] is True
    assert message in result["content"][0]["text"]


def test_external_error_does_not_disclose_credentials(client, monkeypatch, caplog):
    import logging

    secret = "postgresql://private:private-password@db/private"

    def fail(*args):
        raise ValueError(secret)

    monkeypatch.setattr(PostgresReader, "query", fail)
    with caplog.at_level(logging.DEBUG):
        response = rpc(client, "tools/call", {"name": "postgres_query", "arguments": {"sql": "SELECT 1"}})
    assert response.json()["result"]["isError"] is True
    assert secret not in response.text and secret not in caplog.text
    assert "private-password" not in caplog.text


def test_binary_tool_protocol(client, monkeypatch):
    import base64

    monkeypatch.setattr(
        PostgresReader,
        "query",
        lambda *args: {"columns": ["decode"], "rows": [[memoryview(bytes.fromhex("deadbeef"))]]},
    )
    result = rpc(
        client, "tools/call", {"name": "postgres_query", "arguments": {"sql": "SELECT decode('deadbeef', 'hex')"}}
    ).json()["result"]
    assert not result["isError"]
    cell = json.loads(result["content"][0]["text"])["rows"][0][0]
    assert base64.b64decode(cell["content"]).hex() == "deadbeef"


def test_disabled_does_not_import_mcp_dependencies():
    import os
    import subprocess
    import sys

    script = """
import builtins
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "mcp" or name.startswith("mcp.") or name == "pglast":
        raise ImportError("MCP dependency deliberately unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
from finance_analysis.interfaces.api.app import create_app
from fastapi.testclient import TestClient
with TestClient(create_app()) as client:
    assert client.get("/status").status_code == 200
    assert client.post("/mcp/").status_code == 404
import sys
assert "finance_analysis.mcp.redis" not in sys.modules
assert "finance_analysis.mcp.postgres" not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "MCP_ENABLED": "false"},
        check=True,
        capture_output=True,
        text=True,
    )
