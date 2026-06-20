from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> int:
    """Start the FastAPI web/API service."""
    import uvicorn

    from finance_analysis.config import load_env
    from finance_analysis.config.runtime import get_runtime_config
    from finance_analysis.core.logging import setup_backend_logging
    from finance_analysis.core.paths import ensure_data_directories

    load_env()
    ensure_data_directories()
    setup_backend_logging(service="server", log_prefix="web_server")
    config = get_runtime_config()
    host = config.webui_host
    port = config.webui_port
    if not host or port is None:
        print("WEBUI_HOST and WEBUI_PORT must be configured, or pass --host and --port.")
        return 1

    print(f"正在启动 Web 服务: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    print()

    uvicorn.run(
        "finance_analysis.interfaces.api.app:app",
        host=host,
        port=port,
        log_level="info",
    )

    return 0
