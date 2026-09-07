"""CLI for finance-analysis-crypto-stream."""

import asyncio
import logging
import signal

from finance_analysis.crypto.config import get_crypto_config

logger = logging.getLogger(__name__)


async def _run():
    from finance_analysis.crypto.realtime import CryptoRealtime
    from finance_analysis.crypto.service import CryptoService
    from finance_analysis.crypto_stream.service import CryptoStreamService
    from finance_analysis.database.config import get_database_config
    from finance_analysis.database.repositories.crypto import CryptoRepository
    from finance_analysis.integrations.crypto.binance import BinanceClient

    config = get_crypto_config()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not config.enabled:
        logger.info("Crypto disabled; waiting for shutdown")
        await stop.wait()
        return 0
    while not stop.is_set():
        try:
            repository = await asyncio.to_thread(CryptoRepository)
            with repository.stream_leader() as acquired:
                if acquired:
                    service = CryptoService(
                        repository,
                        CryptoRealtime.from_url(get_database_config().redis_url),
                        BinanceClient(config),
                        config,
                    )
                    streamer = CryptoStreamService(service)
                    streamer.stop = stop
                    await streamer.run()
                else:
                    logger.info("Another crypto streamer owns the BTC writer lock")
        except Exception:
            logger.exception("Crypto streamer infrastructure unavailable; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except TimeoutError:
            pass
    return 0


def main():
    from finance_analysis.config import load_env
    from finance_analysis.core.logging import setup_backend_logging
    from finance_analysis.core.paths import ensure_data_directories

    load_env()
    ensure_data_directories()
    setup_backend_logging(service="crypto-streamer", log_prefix="crypto-streamer")
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
