from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def main() -> int:
    """Start the FastAPI API service."""
    import uvicorn

    from finance_analysis.config import load_env
    from finance_analysis.core.logging import setup_backend_logging
    from finance_analysis.core.paths import ensure_data_directories

    load_env()
    ensure_data_directories()
    setup_backend_logging(service="server", log_prefix="server")
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", 8000))
    print(f"正在启动 Finance Analysis API 服务: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    print()

    uvicorn.run(
        "finance_analysis.interfaces.api.app:app",
        host=host,
        port=port,
        log_level="info",
    )

    return 0
