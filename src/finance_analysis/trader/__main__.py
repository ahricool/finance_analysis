"""CLI entry point for finance-analysis-trader."""
import asyncio
import signal


async def _run():
    from finance_analysis.trader.service import TraderService

    service = TraderService()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, service.request_stop)
        except NotImplementedError:
            pass
    return 0 if await service.run() else 1


def main():
    from finance_analysis.config import load_env
    from finance_analysis.core.logging import setup_backend_logging
    from finance_analysis.core.paths import ensure_data_directories

    load_env()
    ensure_data_directories()
    setup_backend_logging(service="trader", log_prefix="trader")
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
