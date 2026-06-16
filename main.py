

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Finance Analysis Web/API service.")
    parser.add_argument("--webui-only", action="store_true", help="Compatibility flag; the service always runs Web/API.")
    parser.add_argument("--host", help="Override WEBUI_HOST from configuration.")
    parser.add_argument("--port", type=int, help="Override WEBUI_PORT from configuration.")
    return parser.parse_args()


def main() -> int:
    """
    启动 Web 服务
    """
    try:
        import uvicorn
        from src.config import get_config, setup_env
        from src.logging_config import setup_backend_logging

        args = _parse_args()
        setup_env()
        setup_backend_logging(service="server", log_prefix="web_server")
        config = get_config()
        host = args.host or config.webui_host
        port = args.port or config.webui_port
        if not host or port is None:
            print("WEBUI_HOST and WEBUI_PORT must be configured, or pass --host and --port.")
            return 1

        print(f"正在启动 Web 服务: http://{host}:{port}")
        print(f"API 文档: http://{host}:{port}/docs")
        print()

        uvicorn.run(
            "api.app:app",
            host=host,
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
