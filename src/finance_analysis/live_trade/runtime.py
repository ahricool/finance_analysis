"""Live account monitoring and read-only public-market strategy observation."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import websockets
from redis.exceptions import RedisError

from finance_analysis.database.repositories import contracts, live_trade as repo
from finance_analysis.integrations.crypto.binance_live import LiveReader, LiveReadError, WS
from finance_analysis.integrations.crypto.account_records import usdt_perpetual_symbols, reconciliation_orders

from finance_analysis.crypto_strategy import observe

from .config import LiveConfig

logger = logging.getLogger(__name__)
STATUS_KEY = "futures:live:v1:connection"
WEEK = 7 * 86400_000


def now_ms():
    return int(time.time() * 1000)


def ms(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


async def db(fn, *args):
    return await asyncio.to_thread(fn, *args)


class LiveMonitor:
    def __init__(self, redis, reader):
        self.redis, self.reader = redis, reader
        self.changed = asyncio.Event()
        self.stream_connected = False
        self.symbols = set()
        self.event_symbols = {}
        self.event_sequence = 0
        self.partial = None

    async def report(self, status, reason=None):
        try:
            await self.redis.set(
                STATUS_KEY,
                json.dumps(
                    {
                        "status": status,
                        "reason": reason,
                        "stream_connected": self.stream_connected,
                    }
                ),
                ex=90,
            )
        except RedisError:
            logger.warning("Binance Live monitor status cache unavailable")

    async def event(self, event):
        kind = event.get("e")
        if kind not in {
            "ACCOUNT_UPDATE",
            "ACCOUNT_CONFIG_UPDATE",
            "ORDER_TRADE_UPDATE",
            "ALGO_UPDATE",
            "CONDITIONAL_ORDER_TRIGGER_REJECT",
        }:
            return
        self.changed.set()
        order = event.get("o", {})
        if order.get("s") in self.symbols:
            self.event_sequence += 1
            self.event_symbols[order["s"]] = self.event_sequence
        if kind != "ORDER_TRADE_UPDATE" or order.get("s") not in self.symbols:
            return
        # Persist actual exchange events by stable ID; REST fills other fields.
        fields = {
            "s": "symbol",
            "i": "orderId",
            "c": "clientOrderId",
            "S": "side",
            "o": "type",
            "X": "status",
            "q": "origQty",
            "z": "executedQty",
            "p": "price",
            "ap": "avgPrice",
            "ps": "positionSide",
            "R": "reduceOnly",
        }
        if not {"s", "i", "X"}.issubset(order):
            return
        row = {target: order[source] for source, target in fields.items() if source in order}
        row["updateTime"] = event["T"]
        if order.get("x") == "NEW":
            row["time"] = event["T"]
        await db(repo.put_records, "order", [row])
        trade_fields = {
            "s": "symbol",
            "t": "id",
            "i": "orderId",
            "S": "side",
            "ps": "positionSide",
            "l": "qty",
            "L": "price",
            "rp": "realizedPnl",
            "n": "commission",
            "N": "commissionAsset",
            "T": "time",
        }
        if order.get("x") == "TRADE" and all(order.get(k) is not None for k in trade_fields):
            await db(repo.put_records, "trade", [{v: order[k] for k, v in trade_fields.items()}])

    async def stream(self):
        quiet = logging.getLogger("live_trade.private_stream")
        quiet.disabled = True
        while True:
            try:
                listen_key = (await self.reader.listen())["listenKey"]
                async with websockets.connect(f"{WS}/ws/{listen_key}", logger=quiet, open_timeout=10) as ws:
                    self.stream_connected = True
                    self.changed.set()
                    renewal = time.monotonic() + 1800
                    while True:
                        if time.monotonic() >= renewal:
                            await self.reader.listen("PUT")
                            renewal = time.monotonic() + 1800
                        try:
                            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        except TimeoutError:
                            continue
                        if event.get("e") == "listenKeyExpired":
                            break
                        await self.event(event)
            except Exception:
                logger.warning("Binance Live private stream unavailable; REST monitoring continues")
            finally:
                self.stream_connected = False
                self.changed.set()
            await asyncio.sleep(5)

    async def history(self, symbol, kind, start, end):
        rows = await self.reader.history(symbol, kind, startTime=start, endTime=end, limit=1000)
        if len(rows) < 1000:
            await db(repo.put_records, kind, rows)
        elif end > start:
            middle = (start + end) // 2
            await self.history(symbol, kind, start, middle)
            await self.history(symbol, kind, middle + 1, end)
        else:
            raise ValueError("LIVE_HISTORY_PAGE_SATURATED")

    async def sync(self):
        self.partial = None
        await self.reader.sync_clock()
        account = await self.reader.account()
        raw_positions = await self.reader.positions()
        balances = await self.reader.balances()
        alias = next((b.get("accountAlias") for b in balances if b.get("accountAlias")), None)
        try:
            await db(repo.bind, alias)
        except ValueError:
            self.symbols.clear()
            raise
        previous, _ = await db(repo.snapshots)
        synced_at = datetime.now(timezone.utc).isoformat()
        self.partial = {
            "account": account,
            "balances": balances,
            "positions": [],
            "open_orders": [],
            "open_algos": [],
            "reconcile_open_orders": reconciliation_orders(previous),
            "complete": False,
            "synced_at": synced_at,
            "last_reconciled_at": (previous or {}).get("last_reconciled_at"),
        }
        self.symbols = usdt_perpetual_symbols(await self.reader.rules())
        positions = [dict(p) for p in raw_positions if p["symbol"] in self.symbols and Decimal(p["positionAmt"])]
        self.partial["positions"] = positions
        configs = {r["symbol"]: r for r in await self.reader.symbol_config()}
        configuration = await self.reader.configuration()
        self.partial["configuration"] = configuration
        for position in positions:
            config = configs.get(position["symbol"], {})
            position.update(
                direction="LONG" if Decimal(position["positionAmt"]) > 0 else "SHORT",
                leverage=config.get("leverage"),
                marginType=config.get("marginType"),
                source="EXTERNAL",
            )
            try:
                rate = await self.reader.funding(position["symbol"])
                position.update(fundingRate=rate.get("lastFundingRate"), nextFundingTime=rate.get("nextFundingTime"))
            except LiveReadError:
                pass
        orders = [
            {**repo.normalize_ids(row), "source": "EXTERNAL"}
            for row in await self.reader.open_orders()
            if row["symbol"] in self.symbols
        ]
        await db(repo.put_records, "order", orders)
        self.partial["open_orders"] = orders
        algos = [
            {**repo.normalize_ids(row), "source": "EXTERNAL"}
            for row in await self.reader.open_orders(True)
            if row["symbol"] in self.symbols
        ]
        await db(repo.put_records, "algo", algos)
        self.partial["open_algos"] = algos
        end = now_ms()
        reconciled = (previous or {}).get("last_reconciled_at")
        start = min(end - 300_000, ms(reconciled) - 300_000) if reconciled else end - WEEK + 1
        if end - start > 90 * 86400_000:
            raise ValueError("LIVE_HISTORY_GAP_TOO_LONG")
        windows = [(cursor, min(cursor + WEEK - 1, end)) for cursor in range(start, end + 1, WEEK)]
        for lower, upper in windows:
            for page in range(1, 101):
                raw = await self.reader.income(startTime=lower, endTime=upper, limit=1000, page=page)
                income = [r for r in raw if not r.get("symbol") or r["symbol"] in self.symbols]
                await db(repo.put_records, "income", income)
                if len(raw) < 1000:
                    break
            else:
                raise ValueError("LIVE_INCOME_PAGE_SATURATED")
        recent_income = await db(repo.records, "income", start)
        symbols = {r["symbol"] for r in positions + orders + algos + recent_income if r.get("symbol")}
        if not reconciled:
            symbols |= {r["symbol"] for r in await db(contracts.contracts)}
        for kind in ("order", "algo"):
            symbols |= {r["symbol"] for r in await db(repo.records, kind, start)}
        event_symbols = dict(self.event_symbols)
        symbols |= event_symbols.keys()
        old_orders = reconciliation_orders(previous)
        symbols |= {r["symbol"] for r in old_orders}
        for symbol in sorted(symbols & self.symbols):
            for kind in ("order", "trade", "algo"):
                for lower, upper in windows:
                    await self.history(symbol, kind, lower, upper)
        # Older open orders might not occur in the recent creation-time window.
        for order in old_orders:
            algo = "algoId" in order
            field = "clientAlgoId" if algo else "clientOrderId"
            if (
                order.get(field)
                and order["symbol"] in self.symbols
                and not any(
                    r.get(field) == order[field] and r["symbol"] == order["symbol"] for r in (algos if algo else orders)
                )
            ):
                try:
                    row = await self.reader.query(order["symbol"], order[field], algo)
                    await db(repo.put_records, "algo" if algo else "order", [row])
                except LiveReadError as exc:
                    if exc.code not in {-2013, -2011}:
                        raise
        view = {
            **self.partial,
            "reconcile_open_orders": [],
            "complete": True,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "last_reconciled_at": datetime.fromtimestamp(end / 1000, timezone.utc).isoformat(),
        }
        await db(repo.save_snapshot, view)
        for symbol, generation in event_symbols.items():
            if self.event_symbols.get(symbol) == generation:
                self.event_symbols.pop(symbol, None)
        self.partial = None
        return view

    async def run(self):
        observer = None
        stream = None
        try:
            while True:
                try:
                    await self.sync()
                    if observer is None:
                        observer = asyncio.create_task(observe.run(self.redis))
                    if stream is None:
                        stream = asyncio.create_task(self.stream())
                    await self.report("CONNECTED")
                except LiveReadError as exc:
                    if self.partial:
                        await db(repo.save_snapshot, self.partial)
                        if stream is None:
                            stream = asyncio.create_task(self.stream())
                    state = "AUTH_FAILED" if exc.code in {401, -2014, -2015, -1022} else "SYNC_FAILED"
                    await self.report(state, str(exc))
                    if exc.code in {418, 429, -1003}:
                        await asyncio.sleep(60)
                except Exception as exc:
                    if self.partial:
                        await db(repo.save_snapshot, self.partial)
                    await self.report(
                        "SYNC_FAILED",
                        (
                            str(exc)
                            if isinstance(exc, ValueError) and str(exc).isupper()
                            else "LIVE_RECONCILIATION_FAILED"
                        ),
                    )
                    logger.warning("Binance Live account synchronization failed")
                try:
                    await asyncio.wait_for(self.changed.wait(), timeout=20)
                except TimeoutError:
                    pass
                self.changed.clear()
                await asyncio.sleep(2)
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
            if stream is not None:
                stream.cancel()
                await asyncio.gather(stream, return_exceptions=True)


async def run_live_monitor(redis):
    config = LiveConfig.from_env()
    if not config.configured:
        return
    reader = LiveReader(config)
    try:
        while True:
            try:
                await LiveMonitor(redis, reader).run()
            except Exception:
                logger.warning("Binance Live monitor interrupted; reconnecting")
                await asyncio.sleep(10)
    finally:
        await reader.close()
