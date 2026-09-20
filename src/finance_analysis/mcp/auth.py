"""Bearer authentication outside all MCP routes, including redirects/downloads."""

import hmac

from starlette.responses import JSONResponse


class MCPAuthMiddleware:
    def __init__(self, app, enabled: bool, api_key: str):
        self.app, self.enabled = app, enabled
        self.expected = ("Bearer " + api_key).encode("ascii") if enabled else b""

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            headers = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
            if not self.enabled:
                return await JSONResponse({"detail": "Not found"}, 404)(scope, receive, send)
            if len(headers) != 1 or not hmac.compare_digest(headers[0], self.expected):
                return await JSONResponse({"detail": "Unauthorized"}, 401, headers={"WWW-Authenticate": "Bearer"})(
                    scope, receive, send
                )
        await self.app(scope, receive, send)
