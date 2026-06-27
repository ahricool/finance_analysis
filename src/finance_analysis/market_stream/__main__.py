"""CLI entry point for ``finance-analysis-stream``."""

from __future__ import annotations

import asyncio
import logging
import signal


async def _run() -> int:
    from finance_analysis.market_stream.service import MarketStreamService

    service = MarketStreamService()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, service.request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            pass
    return 0 if await service.run() else 1


def main() -> int:
    from finance_analysis.config import load_env
    from finance_analysis.core.logging import setup_backend_logging
    from finance_analysis.core.paths import ensure_data_directories

    load_env()
    ensure_data_directories()
    setup_backend_logging(service="streamer", log_prefix="streamer")
    logging.getLogger(__name__).info("启动独立长桥实时行情服务")
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
