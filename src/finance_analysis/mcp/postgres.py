"""Dedicated, short-lived read-only PostgreSQL transactions; never business Sessions."""

import time
from threading import Timer

import psycopg2
from sqlalchemy.engine import make_url

from .security import MAX_RESULT_BYTES, encoded, qualify_functions, validate_sql


class PostgresReader:
    def __init__(self, url):
        self.url = make_url(url)

    def query(self, sql: str, max_rows: int = 500) -> dict:
        kind = validate_sql(sql)
        sql = qualify_functions(sql)
        if not 1 <= max_rows <= 5000:
            raise ValueError("max_rows must be between 1 and 5000")
        start = time.monotonic()
        params = self.url.translate_connect_args(username="user")
        params.update(dict(self.url.query))
        params.update(
            connect_timeout=5,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=10000 -c lock_timeout=2000 -c search_path=pg_catalog,public"
            ),
        )
        conn = psycopg2.connect(**params)

        def cancel_query():
            try:
                conn.cancel()
            except psycopg2.Error:
                pass  # Connection failure is reported by the query, never log DSNs here.

        deadline = Timer(10, cancel_query)
        deadline.daemon = True
        deadline.start()
        try:
            conn.set_session(readonly=True, autocommit=False)
            with conn.cursor() as check:
                check.execute(
                    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
                if any(check.fetchone()):
                    raise ValueError("MCP database role must not have elevated privileges")
            # Named cursors avoid buffering an entire SELECT result in the application.
            cursor = conn.cursor(name="mcp_read") if kind == "SelectStmt" else conn.cursor()
            with cursor:
                cursor.execute(sql)
                first = cursor.fetchmany(1)
                columns = [col.name for col in cursor.description]
                rows, truncated, size = [], False, len(encoded(columns)) + 256
                batch = first
                while batch:
                    row = list(batch[0])
                    row_size = len(encoded(row)) + 1
                    if len(rows) >= max_rows or size + row_size > MAX_RESULT_BYTES:
                        truncated = True
                        break
                    rows.append(row)
                    size += row_size
                    batch = cursor.fetchmany(1)
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
            }
        finally:
            deadline.cancel()
            deadline.join()
            try:
                conn.rollback()
            finally:
                conn.close()
