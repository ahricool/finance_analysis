"""MCP transport mounted in FastAPI; only six low-level read tools."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from .auth import MCPAuthMiddleware
from .config import MCPConfig
from .errors import ReadValidationError
from .serialization import encoded

logger = logging.getLogger(__name__)


def install_mcp(app):
    config = MCPConfig.from_env()
    app.add_middleware(MCPAuthMiddleware, enabled=config.enabled, api_key=config.api_key)
    if not config.enabled:
        return
    # Disabled MCP does not import its SDK, SQL parser or Redis private parser.
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import ToolAnnotations

    from .filesystem import FileReader
    from .postgres import PostgresReader
    from .redis import RedisReader

    files = FileReader()
    postgres = PostgresReader(config.database_url)
    redis = RedisReader(config.redis_url)
    slots = asyncio.Semaphore(4)
    mcp = FastMCP(
        "finance-analysis-diagnostics",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        max_request_body_size=128 * 1024,
        # Bearer authentication is mandatory on every request, including GET.
        # External production hostnames are intentionally supported.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    async def invoke(tool, function, *args):
        start = time.monotonic()
        success = False
        result = {}
        try:
            async with asyncio.timeout(1):
                await slots.acquire()
            try:
                result = await run_in_threadpool(function, *args)
            finally:
                slots.release()
            # Ensure decimals, timestamps and byte values are JSON-safe and stable.
            import json

            result = json.loads(encoded(result))
            success = True
        except ReadValidationError as exc:
            # Only our validation errors are safe to expose. External errors may contain SQL/credentials.
            raise ToolError(str(exc)) from None
        except Exception:
            raise ToolError("Diagnostic read failed or server busy; check path, permissions and connection") from None
        finally:
            logger.info(
                "MCP tool=%s elapsed_ms=%d success=%s result_size=%d",
                tool,
                round((time.monotonic() - start) * 1000),
                success,
                len(encoded(result)),
            )
        return result

    @mcp.tool(annotations=annotations)
    async def postgres_query(sql: str, max_rows: int = 500) -> dict:
        """Read PostgreSQL via SELECT/SHOW/EXPLAIN; 500 default, 5000 maximum rows, 2 MiB output."""
        return await invoke("postgres_query", postgres.query, sql, max_rows)

    @mcp.tool(annotations=annotations)
    async def redis_read(command: str, args: list[str]) -> dict:
        """Execute an allowlisted read command. Raw RESP arrays; strings have content/encoding fields."""
        return await invoke("redis_read", redis.read, command, args)

    @mcp.tool(annotations=annotations)
    async def fs_list(path: str) -> dict:
        """List one directory under /data (up to 2000 entries); / means the data root."""
        return await invoke("fs_list", files.list, path)

    @mcp.tool(annotations=annotations)
    async def fs_stat(path: str) -> dict:
        """Read file/directory metadata under /data. Symlinks are not followed."""
        return await invoke("fs_stat", files.stat, path)

    @mcp.tool(annotations=annotations)
    async def fs_read(path: str, offset: int = 0, max_bytes: int = 256 * 1024) -> dict:
        """Read up to 1 MiB under /data; byte offsets, UTF-8 or base64 for binary data."""
        return await invoke("fs_read", files.read, path, offset, max_bytes)

    @mcp.tool(annotations=annotations)
    async def fs_tail(path: str, lines: int = 200) -> dict:
        """Read the last 200 lines (max 5000), scanning at most the last 1 MiB."""
        return await invoke("fs_tail", files.tail, path, lines)

    @app.get("/mcp/files/{path:path}", include_in_schema=False)
    def download(path: str, request: Request):
        try:
            stream = files.file(path)
        except (OSError, ValueError):
            raise HTTPException(404, "File not available") from None
        import os

        size = os.fstat(stream.fileno()).st_size
        start, end, status = 0, size - 1, 200
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        }
        range_header = request.headers.get("range")
        if range_header:
            import re

            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            try:
                if not match or not any(match.groups()) or not size:
                    raise ValueError()
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), size - 1) if right else size - 1
                else:
                    if int(right) <= 0:
                        raise ValueError()
                    start = max(0, size - int(right))
                if start > end:
                    raise ValueError()
                status = 206
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            except ValueError:
                stream.close()
                raise HTTPException(416, "Invalid range", headers={"Content-Range": f"bytes */{size}"}) from None
        count = max(0, end - start + 1)
        headers["Content-Length"] = str(count)

        def chunks():
            started = time.monotonic()
            remaining = count
            try:
                stream.seek(start)
                remaining = count
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            finally:
                stream.close()
                logger.info(
                    "MCP tool=download elapsed_ms=%d success=%s result_size=%d",
                    round((time.monotonic() - started) * 1000),
                    remaining == 0,
                    count - remaining,
                )

        return StreamingResponse(
            chunks(),
            status_code=status,
            headers=headers,
            media_type="application/octet-stream",
            background=BackgroundTask(stream.close),
        )

    app.mount("/mcp", mcp.streamable_http_app())
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with previous_lifespan(application):
                async with mcp.session_manager.run():
                    yield
        finally:
            redis.close()

    app.router.lifespan_context = lifespan
