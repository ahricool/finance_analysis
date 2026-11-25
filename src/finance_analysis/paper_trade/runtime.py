"""Elected Trader owns all private network I/O and durable order execution."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from decimal import ROUND_CEILING
import uuid

import websockets
from redis.exceptions import RedisError

from finance_analysis.contracts.service import key, read_json
from finance_analysis.database.repositories import contracts, paper_trade as repo
from finance_analysis.integrations.crypto.binance_demo import DemoClient, DemoError, WS
from finance_analysis.integrations.crypto.account_records import usdt_perpetual_symbols, reconciliation_orders

from .config import DemoConfig
from .ledger import attributed_trades, ownership, performance
from .strategies import WINDOW_STRATEGIES, perpetual_drive as drive
from .strategy import D, STRATEGIES, closed_closes, contract_rule, filters, floor_step, sized_quantity, validate_order

logger = logging.getLogger(__name__)
STATUS_KEY = "futures:paper:v1:connection"
TERMINAL = {
    "FILLED": "FILLED",
    "CANCELED": "CANCELED",
    "EXPIRED": "CANCELED",
    "EXPIRED_IN_MATCH": "CANCELED",
    "REJECTED": "FAILED",
    "FINISHED": "FINISHED",
}
WEEK = 7 * 86400_000


def now_ms():
    return int(time.time() * 1000)


def ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


async def db(fn, *args):
    return await asyncio.to_thread(fn, *args)


def position_for(positions, symbol, side="BOTH"):
    return next(
        (p for p in positions if p["symbol"] == symbol and p["positionSide"] == side and D(p["positionAmt"])), None
    )


def order_state(row, algo):
    status = row.get("algoStatus" if algo else "status")
    return TERMINAL.get(status, "PARTIALLY_FILLED" if status == "PARTIALLY_FILLED" else "SUBMITTED")


class PaperRuntime:
    def __init__(self, redis, client, leader):
        self.redis, self.client, self.leader = redis, client, leader
        self.changed = asyncio.Event()
        self.stream_connected = False
        self.rules = []
        self.view = None
        self.basic_view = None
        self.event_symbols = {}
        self.event_sequence = 0

    async def connection(self, state, reason=None):
        try:
            await self.redis.set(
                STATUS_KEY,
                json.dumps(
                    {
                        "status": state,
                        "stream_connected": self.stream_connected,
                        "reason": reason,
                    }
                ),
                ex=90,
            )
            return True
        except RedisError:
            logger.warning("Binance Demo connection status cache unavailable")
            return False

    async def stream_event(self, event):
        kind = event.get("e")
        if kind not in {
            "ACCOUNT_UPDATE",
            "ORDER_TRADE_UPDATE",
            "ALGO_UPDATE",
            "ACCOUNT_CONFIG_UPDATE",
            "CONDITIONAL_ORDER_TRIGGER_REJECT",
        }:
            return
        order = event.get("o", {})
        if order.get("s"):
            self.event_sequence += 1
            self.event_symbols[order["s"]] = self.event_sequence
        if (
            kind == "ORDER_TRADE_UPDATE"
            and self.view
            and self.view.get("account_alias")
            and order.get("s") in usdt_perpetual_symbols(self.rules)
        ):
            normalized = {
                "symbol": order["s"],
                "orderId": order["i"],
                "clientOrderId": order["c"],
                "side": order["S"],
                "type": order["o"],
                "status": order["X"],
                "origQty": order["q"],
                "executedQty": order["z"],
                "price": order["p"],
                "avgPrice": order["ap"],
                "positionSide": order["ps"],
                "reduceOnly": order["R"],
                "updateTime": event["T"],
            }
            if order["x"] == "NEW":
                normalized["time"] = event["T"]
            await db(repo.put_records, "order", [normalized])
            if order["x"] == "TRADE" and D(order["l"]) > 0:
                # Do not manufacture a fee when the event omits it; REST fills
                # the complete record on reconciliation.
                if order.get("N") and order.get("n") is not None:
                    await db(
                        repo.put_records,
                        "trade",
                        [
                            {
                                "symbol": order["s"],
                                "id": order["t"],
                                "orderId": order["i"],
                                "side": order["S"],
                                "positionSide": order["ps"],
                                "qty": order["l"],
                                "price": order["L"],
                                "realizedPnl": order["rp"],
                                "commission": order["n"],
                                "commissionAsset": order["N"],
                                "time": order["T"],
                            }
                        ],
                    )
        self.changed.set()

    async def stream(self):
        # Do not use the default WebSocket logger, which can include listenKey URLs.
        quiet = logging.getLogger("paper_trade.private_stream")
        quiet.disabled = True
        while True:
            try:
                listen_key = (await self.client.listen())["listenKey"]
                async with websockets.connect(f"{WS}/private/ws/{listen_key}", logger=quiet, open_timeout=10) as ws:
                    self.stream_connected = True
                    self.changed.set()
                    renew_at = time.monotonic() + 1800
                    while True:
                        if time.monotonic() >= renew_at:
                            await self.client.listen("PUT")
                            renew_at = time.monotonic() + 1800
                        try:
                            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        except TimeoutError:
                            continue
                        if event.get("e") == "listenKeyExpired":
                            break
                        await self.stream_event(event)
            except Exception:
                logger.warning("Binance Demo user stream unavailable; REST reconciliation remains active")
            finally:
                self.stream_connected = False
                self.changed.set()
            await asyncio.sleep(5)

    async def history(self, symbol, kind, start, end):
        # Binance limits REST history windows to seven days. A saturated page
        # is split by time; if indivisible, block execution rather than lose fills.
        rows = await self.client.history(symbol, kind, startTime=start, endTime=end, limit=1000)
        if len(rows) < 1000:
            await db(repo.put_records, kind, rows)
        elif end > start:
            mid = (start + end) // 2
            await self.history(symbol, kind, start, mid)
            await self.history(symbol, kind, mid + 1, end)
        else:
            raise ValueError("HISTORY_PAGE_SATURATED")

    async def sync(self):
        self.basic_view = None
        sync_started = now_ms()
        await self.client.sync_clock()
        account = await self.client.account()
        positions = await self.client.positions()
        balances = await self.client.balances()
        alias = next((b.get("accountAlias") for b in balances if b.get("accountAlias")), None)
        try:
            await db(repo.bind_account, alias)
        except ValueError:
            self.view = None
            self.rules = []
            raise
        previous, _ = await db(repo.snapshots)
        self.basic_view = {
            **(previous or {}),
            "account": account,
            "positions": [],
            "reconcile_open_orders": reconciliation_orders(previous),
            "account_alias": alias,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "complete": False,
        }
        configuration = await self.client.configuration()
        configs = await self.client.symbol_config()
        self.rules = await self.client.rules()
        supported = usdt_perpetual_symbols(self.rules)
        positions = [p for p in positions if p["symbol"] in supported]
        self.basic_view["positions"] = [p for p in positions if D(p["positionAmt"])]
        shared = await db(contracts.contracts)
        demo_symbols = [
            r["symbol"]
            for r in self.rules
            if r.get("status") == "TRADING"
            and r.get("quoteAsset") == "USDT"
            and r.get("marginAsset") == "USDT"
            and r.get("contractType") in {"PERPETUAL", "TRADIFI_PERPETUAL"}
        ]
        demo_coin_symbols = [
            r["symbol"] for r in self.rules if r["symbol"] in demo_symbols and r.get("underlyingType") == "COIN"
        ]
        self.basic_view.update(
            configuration=configuration,
            symbol_config=configs,
            demo_symbols=demo_symbols,
            demo_coin_symbols=demo_coin_symbols,
            shared_symbols=[r["symbol"] for r in shared],
        )
        orders = [repo.normalize_ids(r) for r in await self.client.open_orders() if r["symbol"] in supported]
        await db(repo.put_records, "order", orders)
        self.basic_view["open_orders"] = orders
        algos = [repo.normalize_ids(r) for r in await self.client.open_orders(True) if r["symbol"] in supported]
        await db(repo.put_records, "algo", algos)
        self.basic_view["open_algos"] = algos
        end = now_ms()
        previous_sync = (previous or {}).get("last_reconciled_at")
        start = min(end - 300_000, ms(previous_sync) - 300_000) if previous_sync else end - WEEK + 1
        if end - start > 90 * 86400_000:
            raise ValueError("DEMO_HISTORY_GAP_TOO_LONG")
        windows = [(cursor, min(cursor + WEEK - 1, end)) for cursor in range(start, end + 1, WEEK)]
        # Pull recent income account-wide so App trades outside the watchlist are discovered.
        for lower, upper in windows:
            page = 1
            while True:
                income = await self.client.income(startTime=lower, endTime=upper, limit=1000, page=page)
                await db(
                    repo.put_records, "income", [r for r in income if not r.get("symbol") or r["symbol"] in supported]
                )
                if len(income) < 1000:
                    break
                page += 1
                if page > 100:
                    raise ValueError("INCOME_HISTORY_SATURATED")
        income = await db(repo.records, "income")
        strategies = await db(repo.strategies)
        recent_income = [r for r in income if r["time"] >= start]
        active_intents = await db(repo.intents, True)
        symbols = {
            r["symbol"]
            for r in positions + orders + algos + recent_income + active_intents + strategies
            if r.get("symbol")
        }
        for kind in ("order", "algo"):
            symbols |= {
                r["symbol"]
                for r in await db(repo.records, kind)
                if int(r.get("updateTime", r.get("time", r.get("createTime", 0)))) >= start
            }
        event_symbols = dict(self.event_symbols)
        symbols |= event_symbols.keys()
        if not previous_sync:
            symbols |= {r["symbol"] for r in shared}
        # Include known previously open App orders even if now canceled.
        previous_orders = reconciliation_orders(previous)
        symbols |= {r["symbol"] for r in previous_orders}
        for symbol in sorted(symbols & supported):
            for kind in ("order", "trade", "algo"):
                for lower, upper in windows:
                    await self.history(symbol, kind, lower, upper)
        for old in previous_orders:
            algo = "algoId" in old
            field = "clientAlgoId" if algo else "clientOrderId"
            if (
                old["symbol"] in supported
                and old.get(field)
                and not any(
                    r.get(field) == old[field] and r["symbol"] == old["symbol"] for r in (algos if algo else orders)
                )
            ):
                try:
                    row = await self.client.query(old["symbol"], old[field], algo)
                    await db(repo.put_records, "algo" if algo else "order", [row])
                except DemoError as exc:
                    if exc.code not in {-2013, -2011}:
                        raise
        # Query every pending FA intent by its original stable exchange client ID.
        for intent in await db(repo.intents, True):
            if intent["status"] == "QUEUED":
                continue
            if intent["action"] == "CANCEL":
                # REST reconciliation is authoritative; never resubmit an uncertain cancellation.
                target = intent["payload"]["exchange_id"]
                rows = algos if intent["payload"]["algo"] else orders
                field = "algoId" if intent["payload"]["algo"] else "orderId"
                if not any(str(r[field]) == target and r["symbol"] == intent["symbol"] for r in rows):
                    known = await db(repo.records, "algo" if intent["payload"]["algo"] else "order")
                    row = next((r for r in known if str(r[field]) == target and r["symbol"] == intent["symbol"]), None)
                    state = order_state(row, intent["payload"]["algo"]) if row else "UNKNOWN"
                    await db(
                        repo.transition,
                        intent["id"],
                        (
                            "CANCELED"
                            if state == "CANCELED"
                            else "FINISHED" if state in {"FILLED", "FINISHED"} else "UNKNOWN"
                        ),
                        None if state in {"CANCELED", "FILLED", "FINISHED"} else "CANCEL_RECONCILIATION_PENDING",
                    )
                continue
            is_algo = bool(intent["payload"].get("algo"))
            try:
                row = await self.client.query(intent["symbol"], intent["id"], is_algo)
                await db(repo.put_records, "algo" if is_algo else "order", [row])
                row = (
                    await db(
                        repo.get_record,
                        "algo" if is_algo else "order",
                        intent["symbol"],
                        str(row["algoId" if is_algo else "orderId"]),
                    )
                    or row
                )
                state = order_state(row, is_algo)
                if is_algo and state == "FINISHED" and row.get("actualOrderId"):
                    child = next(
                        (
                            r
                            for r in await db(repo.records, "order")
                            if r["symbol"] == intent["symbol"] and str(r["orderId"]) == str(row["actualOrderId"])
                        ),
                        None,
                    )
                    if child:
                        state = order_state(child, False)
                await db(repo.transition, intent["id"], state)
            except DemoError as exc:
                if exc.code not in {-2013, -2011}:
                    raise
                # A recent stream record can be newer than the query. Never
                # retry a possibly accepted write, even if not yet visible.
                field = "clientAlgoId" if is_algo else "clientOrderId"
                known = next(
                    (
                        r
                        for r in await db(repo.records, "algo" if is_algo else "order")
                        if r.get(field) == intent["id"] and r["symbol"] == intent["symbol"]
                    ),
                    None,
                )
                await db(
                    repo.transition,
                    intent["id"],
                    order_state(known, is_algo) if known else "UNKNOWN",
                    None if known else "RECONCILIATION_PENDING",
                )
        all_orders, all_algos, trades = [await db(repo.records, k) for k in ("order", "algo", "trade")]
        intents = await db(repo.intents)
        trades = attributed_trades(intents, all_orders, all_algos, trades)
        funding = {}
        for symbol in {p["symbol"] for p in positions if D(p["positionAmt"])}:
            try:
                funding[symbol] = await self.client.funding(symbol)
            except DemoError:
                # Rate display is optional; accounting uses actual income.
                funding[symbol] = {}
        for p in positions:
            _, managed, conflict = ownership(p["symbol"], positions, trades)
            p["source"] = (
                "STRATEGY"
                if managed
                else "CONFLICT" if conflict and any(s["symbol"] == p["symbol"] for s in strategies) else "EXTERNAL"
            )
            c = next((r for r in configs if r["symbol"] == p["symbol"]), {})
            p["leverage"] = c.get("leverage")
            p["direction"] = "LONG" if D(p["positionAmt"]) > 0 else "SHORT"
            p["marginType"] = c.get("marginType")
            p["fundingRate"] = funding.get(p["symbol"], {}).get("lastFundingRate")
            p["nextFundingTime"] = funding.get(p["symbol"], {}).get("nextFundingTime")
        self.view = {
            "account": account,
            "positions": [p for p in positions if D(p["positionAmt"])],
            "account_alias": alias,
            "complete": True,
            "sync_started": sync_started,
            "last_reconciled_at": datetime.fromtimestamp(end / 1000, timezone.utc).isoformat(),
            "configuration": configuration,
            "symbol_config": configs,
            "open_orders": orders,
            "open_algos": algos,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "shared_symbols": [r["symbol"] for r in shared],
            "demo_symbols": demo_symbols,
            "demo_coin_symbols": demo_coin_symbols,
        }
        await db(repo.save_snapshot, self.view)
        for symbol, generation in event_symbols.items():
            if self.event_symbols.get(symbol) == generation:
                self.event_symbols.pop(symbol, None)
        self.basic_view = None
        return trades, income

    async def submit(self, intent, trades):
        i, symbol, payload = intent["id"], intent["symbol"], intent["payload"]
        if not await self.leader.renew():
            return
        if now_ms() - ms(intent["created_at"]) > 120_000 or (
            intent["bar_time"] and now_ms() - intent["bar_time"] > 90_000
        ):
            await db(repo.transition, i, "BLOCKED", "INTENT_EXPIRED", None, "QUEUED")
            return
        if now_ms() - self.view["sync_started"] > 60_000:
            return
        strategy = next((s for s in await db(repo.strategies) if s["symbol"] == intent["strategy"]), None)
        pos = position_for(self.view["positions"], symbol)
        actual, managed, conflict = ownership(symbol, self.view["positions"], trades)
        claimed = False
        try:
            if intent["action"] == "CANCEL":
                algo = payload["algo"]
                rows = self.view["open_algos"] if algo else self.view["open_orders"]
                field = "algoId" if algo else "orderId"
                if not any(str(r[field]) == payload["exchange_id"] and r["symbol"] == symbol for r in rows):
                    raise ValueError("ORDER_NOT_OPEN")
                if not await self.leader.renew():
                    return
                if not await db(repo.transition, i, "SUBMITTING", None, None, "QUEUED"):
                    return
                claimed = True
                await self.client.cancel(symbol, payload["exchange_id"], algo)
                await db(repo.transition, i, "SUBMITTED", "AWAITING_RECONCILIATION")
                return
            if any(
                other["symbol"] == symbol and other["id"] != i and other["status"] in {"UNKNOWN", "SUBMITTING"}
                for other in await db(repo.intents, True)
            ):
                raise ValueError("UNRESOLVED_ORDER")
            if self.view["configuration"].get("dualSidePosition") is not False:
                raise ValueError("ONE_WAY_MODE_REQUIRED")
            if self.view["configuration"].get("canTrade") is not True:
                raise ValueError("DEMO_TRADE_PERMISSION_REQUIRED")
            rule = contract_rule(self.rules, symbol)
            if rule.get("underlyingType") != "COIN":
                schedule = await self.client.schedule()
                market = schedule.get("marketSchedules", {}).get(rule.get("underlyingType"), {})
                if not any(
                    s["startTime"] <= now_ms() < s["endTime"]
                    and s["type"] in {"REGULAR", "PRE_MARKET", "AFTER_MARKET", "OVERNIGHT"}
                    for s in market.get("sessions", [])
                ):
                    raise ValueError("DEMO_TRADING_SESSION_UNVERIFIED")
            quote = await self.client.quote(symbol)
            price = D(quote["price"])
            if price <= 0 or abs(now_ms() - int(quote.get("time", 0))) > 60_000:
                raise ValueError("DEMO_QUOTE_STALE")
            if intent["action"] == "CLOSE":
                if not pos or (strategy and not managed):
                    raise ValueError("NO_OWNED_POSITION")
                if (payload.get("expected_quantity") is not None and D(payload["expected_quantity"]) != actual) or (
                    payload.get("expected_entry_price") is not None
                    and D(payload["expected_entry_price"]) != D(pos["entryPrice"])
                ):
                    raise ValueError("POSITION_CHANGED_CONFIRM_AGAIN")
                order = {
                    "type": "MARKET",
                    "quantity": str(abs(actual)),
                    "side": "SELL" if actual > 0 else "BUY",
                    "reduceOnly": "true",
                }
            elif intent["action"] == "SIGNAL":
                if strategy and strategy["strategy_type"] == drive.TYPE:
                    if rule.get("underlyingType") != "COIN":
                        raise ValueError("DRIVE_CRYPTO_ONLY")
                    if drive.BENCHMARK not in self.view["shared_symbols"]:
                        raise ValueError("DRIVE_BENCHMARK_REMOVED")
                    if payload.get("strategy_type") != drive.TYPE or not drive.valid_profile(
                        payload.get("exit_profile"), strategy["stop_pct"]
                    ):
                        raise ValueError("DRIVE_ENTRY_PROFILE_MISSING")
                if (
                    not strategy
                    or not strategy["enabled"]
                    or conflict
                    or actual
                    or symbol not in self.view["shared_symbols"]
                ):
                    raise ValueError("STRATEGY_PAUSED_OR_POSITION_CONFLICT")
                if any(r["symbol"] == symbol for r in self.view["open_orders"] + self.view["open_algos"]):
                    raise ValueError("OPEN_ORDER_CONFLICT")
                c = next((r for r in self.view["symbol_config"] if r["symbol"] == symbol), {})
                leverage = D(c.get("leverage", 0))
                if not 0 < leverage <= strategy["leverage_limit"]:
                    raise ValueError("LEVERAGE_LIMIT")
                notional = D(strategy["notional"])
                margin = notional / leverage
                if (
                    notional > D(strategy["max_position"])
                    or margin > D(strategy["margin"])
                    or margin > D(self.view["account"]["availableBalance"])
                ):
                    raise ValueError("MARGIN_LIMIT")
                if abs(price / D(payload["production_close"]) - 1) > D("0.02"):
                    raise ValueError("DEMO_PRICE_DIVERGENCE")
                if payload["direction"] == "SHORT" and strategy["direction"] == "LONG":
                    raise ValueError("DIRECTION_DISABLED")
                qty = sized_quantity(rule, notional, price)
                order = {
                    "type": "MARKET",
                    "quantity": str(qty),
                    "side": "BUY" if payload["direction"] == "LONG" else "SELL",
                }
            elif intent["action"] == "PROTECT":
                if not pos or not managed:
                    raise ValueError("NO_OWNED_POSITION")
                stop_ratio = min(D(strategy["stop_pct"]) / 100, D(payload.get("initial_stop", "1")))
                if stop_ratio <= 0:
                    raise ValueError("INVALID_PROTECTION_STOP")
                stop = D(pos["entryPrice"]) * (1 - stop_ratio if actual > 0 else 1 + stop_ratio)
                tick = filters(rule)["PRICE_FILTER"]["tickSize"]
                trigger = (
                    (stop / D(tick)).to_integral_value(rounding=ROUND_CEILING) * D(tick)
                    if "initial_stop" in payload and actual > 0 else floor_step(stop, tick)
                )
                order = {
                    "type": "STOP_MARKET",
                    "side": "SELL" if actual > 0 else "BUY",
                    "quantity": str(abs(actual)),
                    "triggerPrice": str(trigger),
                    "reduceOnly": "true",
                    "workingType": "MARK_PRICE",
                }
            else:
                if managed or (
                    conflict and any(s["symbol"] == symbol and s["enabled"] for s in await db(repo.strategies))
                ):
                    raise ValueError("STRATEGY_POSITION_CONFLICT")
                order = {"type": payload["order_type"], "side": payload["side"], "quantity": payload["quantity"]}
                if payload.get("price"):
                    order.update(price=payload["price"], timeInForce="GTC")
                if payload.get("trigger_price"):
                    order["triggerPrice"] = payload["trigger_price"]
                if payload["reduce_only"]:
                    if (
                        not actual
                        or (actual > 0 and payload["side"] != "SELL")
                        or (actual < 0 and payload["side"] != "BUY")
                        or D(payload["quantity"]) > abs(actual)
                    ):
                        raise ValueError("REDUCE_ONLY_POSITION_MISMATCH")
                    order["reduceOnly"] = "true"
            validate_order(rule, order, price)
            for field in ("quantity", "price", "triggerPrice"):
                if field in order:
                    order[field] = format(D(order[field]), "f")
            algo = order["type"] in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
            order.update(symbol=symbol, positionSide="BOTH")
            if algo:
                order.update(algoType="CONDITIONAL", clientAlgoId=i)
            else:
                order.update(newClientOrderId=i, newOrderRespType="ACK")
            # Recheck pause immediately before an opening order. The durable
            # SUBMITTING transition precedes network I/O, including crashes.
            if intent["action"] == "SIGNAL" and not any(
                s["symbol"] == symbol and s["enabled"] for s in await db(repo.strategies)
            ):
                raise ValueError("PAUSED")
            payload = {**payload, "algo": algo, "exchange_request": order}
            latest_positions = await self.client.positions()
            if intent["action"] == "SIGNAL":
                if any(p["symbol"] == symbol and D(p["positionAmt"]) for p in latest_positions):
                    raise ValueError("EXTERNAL_POSITION_CONFLICT")
                if any(
                    r["symbol"] == symbol for r in await self.client.open_orders() + await self.client.open_orders(True)
                ):
                    raise ValueError("OPEN_ORDER_CONFLICT")
                if D((await self.client.account())["availableBalance"]) < margin:
                    raise ValueError("MARGIN_LIMIT")
            elif intent["action"] in {"CLOSE", "PROTECT"}:
                recent = position_for(latest_positions, symbol)
                if not recent or D(recent["positionAmt"]) != actual or D(recent["entryPrice"]) != D(pos["entryPrice"]):
                    raise ValueError("POSITION_CHANGED_CONFIRM_AGAIN")
            if intent["bar_time"] and now_ms() - intent["bar_time"] > 90_000:
                raise ValueError("SIGNAL_EXPIRED")
            if not await self.leader.renew():
                return
            if not await db(repo.claim, i, symbol, intent["action"], payload):
                return
            claimed = True
            row = await self.client.submit(order, algo)
            await db(repo.put_records, "algo" if algo else "order", [row])
            await db(repo.transition, i, order_state(row, algo))
        except DemoError as exc:
            await db(
                repo.transition,
                i,
                "UNKNOWN" if claimed and exc.uncertain else "FAILED",
                str(exc),
                None,
                "SUBMITTING" if claimed else "QUEUED",
            )
        except (ValueError, KeyError, ArithmeticError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "INVALID_DEMO_DATA"
            await db(
                repo.transition,
                i,
                "UNKNOWN" if claimed else "BLOCKED",
                reason[:128],
                None,
                "SUBMITTING" if claimed else "QUEUED",
            )

    async def evaluate(self, trades, income):
        for strategy in await db(repo.strategies):
            if self.view["configuration"].get("dualSidePosition") is not False:
                await db(repo.status, strategy["symbol"], "ONE_WAY_MODE_REQUIRED")
                continue
            try:
                await self.evaluate_strategy(strategy, trades, income)
            except (ValueError, KeyError, ArithmeticError):
                await db(repo.status, strategy["symbol"], "INVALID_STRATEGY_DATA")

    async def drive_position(self, symbol, position, actual, trades, active):
        """Advance the frozen V8 exit ladder on exchange marks, even when paused."""
        entries = [t for t in trades if t["symbol"] == symbol and t["strategy"] == symbol
                   and t.get("intent_action") == "SIGNAL"]
        if not entries:
            await db(repo.status, symbol, "DRIVE_ENTRY_PROFILE_MISSING")
            return {}, False
        entry = max(entries, key=lambda t: (t["time"], int(t["id"])))
        intent = await db(repo.get_intent, entry["intent_id"])
        profile = (intent or {}).get("payload", {}).get("exit_profile")
        if not profile:
            await db(repo.status, symbol, "DRIVE_ENTRY_PROFILE_MISSING")
            return {}, False
        payload = intent["payload"]
        try:
            stage, triggered = drive.ratchet(
                profile, payload.get("ratchet_stage", 0), position["entryPrice"], position["markPrice"], actual
            )
        except (KeyError, ValueError, ArithmeticError):
            await db(repo.status, symbol, "DRIVE_MARK_UNAVAILABLE")
            stage, triggered = payload.get("ratchet_stage", 0), payload.get("ratchet_triggered", False)
        stage, triggered = await db(repo.drive_ratchet, intent["id"], stage, triggered)
        if triggered:
            if not any(i["action"] == "CLOSE" for i in active):
                close_id = uuid.uuid5(
                    uuid.NAMESPACE_URL, f"paper-drive-exit:{intent['id']}:{actual.normalize()}"
                ).hex
                existing = await db(repo.get_intent, close_id)
                # A queued close may expire before being sent, e.g. during downtime.
                # Only an explicitly unclaimed terminal intent can be replaced.
                while (existing and existing["status"] == "BLOCKED"
                       and existing["reason"] in {"INTENT_EXPIRED", "POSITION_CHANGED_CONFIRM_AGAIN"}
                       and not existing["payload"].get("exchange_request")):
                    close_id = uuid.uuid5(uuid.NAMESPACE_URL, f"paper-drive-retry:{close_id}").hex
                    existing = await db(repo.get_intent, close_id)
                queued = existing or await db(
                    repo.queue, close_id, symbol, "CLOSE",
                    {"exit_reason": "DRIVE_RATCHET" if stage else "DRIVE_INITIAL_STOP",
                     "entry_intent": intent["id"]}, symbol,
                )
                await db(repo.status, symbol, "DRIVE_EXIT_" + queued["status"])
            return {"initial_stop": profile["initial_stop"]}, True
        return {"initial_stop": profile["initial_stop"]}, False

    async def evaluate_strategy(self, strategy, trades, income):
        symbol = strategy["symbol"]
        actual, managed, conflict = ownership(symbol, self.view["positions"], trades)
        active = [i for i in await db(repo.intents, True) if i["symbol"] == symbol]
        if conflict:
            await db(repo.status, symbol, "EXTERNAL_POSITION_CONFLICT")
        if not actual and not conflict:
            for protection in (r for r in self.view["open_algos"] if r["symbol"] == symbol):
                original = next(
                    (i for i in active if i["id"] == protection.get("clientAlgoId") and i["action"] == "PROTECT"),
                    None,
                )
                if original and not any(i["action"] == "CANCEL" for i in active):
                    await db(
                        repo.queue,
                        uuid.uuid4().hex,
                        symbol,
                        "CANCEL",
                        {"algo": True, "exchange_id": str(protection["algoId"])},
                        symbol,
                    )
                    break
        if managed:
            protection_payload = {}
            drive_exit = False
            if strategy["strategy_type"] == drive.TYPE:
                position = position_for(self.view["positions"], symbol)
                protection_payload, drive_exit = await self.drive_position(symbol, position, actual, trades, active)
            # Keep the already-created exchange protection alive while paused.
            protection = [i for i in active if i["action"] == "PROTECT"]
            entries = [t for t in trades if t["symbol"] == symbol and t["strategy"] == symbol]
            last_entry = max(t["time"] for t in entries)
            protect_id = uuid.uuid5(uuid.NAMESPACE_URL, f"paper-stop:{symbol}:{last_entry}:{actual.normalize()}").hex
            if not protection:
                existing = next((i for i in await db(repo.intents) if i["id"] == protect_id), None)
                if not existing:
                    await db(repo.queue, protect_id, symbol, "PROTECT", protection_payload, symbol)
                else:
                    await db(repo.status, symbol, "PROTECTION_MISSING")
            else:
                stop = next(
                    (r for r in self.view["open_algos"] if any(i["id"] == r.get("clientAlgoId") for i in protection)),
                    None,
                )
                if stop and D(stop["quantity"]) != abs(actual):
                    if not any(i["action"] == "CANCEL" for i in active):
                        cancel_id = uuid.uuid5(uuid.NAMESPACE_URL, f"paper-resize:{symbol}:{stop['algoId']}").hex
                        await db(
                            repo.queue,
                            cancel_id,
                            symbol,
                            "CANCEL",
                            {"algo": True, "exchange_id": str(stop["algoId"])},
                            symbol,
                        )
                    await db(repo.status, symbol, "PROTECTION_RESIZE_PENDING")
            if drive_exit:
                return
            unrealized = D(position_for(self.view["positions"], symbol)["unRealizedProfit"])
            realized = D(performance(symbol, trades, income, strategy["strategy_type"])["net"] or 0)
            position = position_for(self.view["positions"], symbol)
            stop_loss = abs(actual) * D(position["entryPrice"]) * D(strategy["stop_pct"]) / 100
            if min(unrealized, realized + unrealized) <= -D(strategy["max_loss"]) or unrealized <= -stop_loss:
                if not any(i["action"] == "CLOSE" for i in active):
                    last_entry = max(t["time"] for t in trades if t["symbol"] == symbol and t["strategy"] == symbol)
                    close_id = uuid.uuid5(uuid.NAMESPACE_URL, f"paper-risk:{symbol}:{last_entry}").hex
                    await db(repo.queue, close_id, symbol, "CLOSE", {}, symbol)
                return
        if symbol not in self.view["shared_symbols"]:
            await db(repo.status, symbol, "SIGNAL_SOURCE_REMOVED")
            return
        bars = await read_json(self.redis, key(symbol, "minute"), [])
        stamp = now_ms()
        if strategy["strategy_type"] == drive.TYPE:
            if drive.BENCHMARK not in self.view["shared_symbols"]:
                await db(repo.status, symbol, "DRIVE_BENCHMARK_REMOVED")
                return
            try:
                rule = contract_rule(self.rules, symbol)
            except ValueError as exc:
                await db(repo.status, symbol, str(exc))
                return
            if rule.get("underlyingType") != "COIN":
                await db(repo.status, symbol, "DRIVE_CRYPTO_ONLY")
                return
            # Same durable closed-5m cursor as EMA; avoid daily reads between decisions.
            if stamp // drive.PERIOD * drive.PERIOD <= strategy["cursor"]:
                return
            if not 15_000 <= stamp % drive.PERIOD <= 90_000:
                return
            benchmark = bars if symbol == drive.BENCHMARK else await read_json(
                self.redis, key(drive.BENCHMARK, "minute"), []
            )
            daily = await db(contracts.daily, symbol, 17)
            signal = WINDOW_STRATEGIES[strategy["strategy_type"]](bars, benchmark, daily, stamp, strategy)
        else:
            closed = closed_closes(bars, stamp, strategy["slow"] * 3 + 1)
            signal = None
            if closed:
                bar, closes = closed
                direction, evidence = STRATEGIES[strategy["strategy_type"]](closes, strategy)
                signal = bar, direction, {**evidence, "production_close": str(closes[-1]), "strategy_type": strategy["strategy_type"]}
        if not signal:
            if strategy["enabled"] and not managed and not conflict and not active:
                await db(repo.status, symbol, "WAITING_FRESH_CLOSED_BARS")
            return
        bar, direction, evidence = signal
        if not direction:
            await db(repo.signal, symbol, bar, {}, None, None, strategy["updated_at"])
            return
        reason = "EXTERNAL_POSITION_CONFLICT" if conflict else None
        action = "SIGNAL"
        if managed:
            if strategy["strategy_type"] != drive.TYPE and (
                (actual > 0 and direction == "SHORT") or (actual < 0 and direction == "LONG")
            ):
                action = "CLOSE"
            else:
                reason = "POSITION_ALREADY_OPEN"
        if any(i["action"] != "PROTECT" or i["status"] in {"UNKNOWN", "SUBMITTING"} for i in active):
            reason = "PENDING_INTENT"
        stats = performance(symbol, trades, income, strategy["strategy_type"])
        if not managed and stats["net"] is not None and D(stats["net"]) <= -D(strategy["max_loss"]):
            reason = "MAX_LOSS_REACHED"
        await db(
            repo.signal,
            symbol,
            bar,
            {**evidence, "direction": direction},
            action,
            reason,
            strategy["updated_at"],
        )

    async def run(self):
        stream = None
        warm = False
        try:
            while True:
                try:
                    trades, income = await self.sync()
                    if stream is None:
                        stream = asyncio.create_task(self.stream())
                    if not await self.connection("CONNECTED"):
                        raise RedisError("Demo connection cache unavailable")
                    if not warm:
                        await db(repo.skip_previous_bars, now_ms() // 300_000 * 300_000)
                        warm = True
                    await self.evaluate(trades, income)
                    # One side effect per reconciliation. Prevent two commands
                    # from using the same stale account/position snapshot.
                    pending = await db(repo.intents, True)
                    queued = [i for i in pending if i["status"] == "QUEUED"]
                    priority = {"CLOSE": 0, "CANCEL": 1, "PROTECT": 2}
                    queued.sort(key=lambda i: priority.get(i["action"], 3))
                    if queued and not self.changed.is_set():
                        await self.submit(queued[0], trades)
                        self.changed.set()
                except DemoError as exc:
                    if self.basic_view:
                        await db(repo.save_snapshot, self.basic_view)
                    warm = False
                    state = (
                        "AUTH_FAILED"
                        if exc.code in {401, -2014, -2015, -1022}
                        else "DEGRADED" if self.basic_view else "UNAVAILABLE"
                    )
                    await self.connection(state, str(exc))
                    if exc.code in {418, 429, -1003}:
                        await asyncio.sleep(60)
                except Exception as exc:
                    if self.basic_view:
                        await db(repo.save_snapshot, self.basic_view)
                    warm = False
                    logger.warning("Binance Demo reconciliation failed")
                    await self.connection(
                        "DEGRADED" if self.basic_view else "UNAVAILABLE",
                        str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "RECONCILIATION_FAILED",
                    )
                try:
                    await asyncio.wait_for(self.changed.wait(), timeout=20)
                except TimeoutError:
                    pass
                self.changed.clear()
                await asyncio.sleep(2)
        finally:
            if stream:
                stream.cancel()
                await asyncio.gather(stream, return_exceptions=True)


async def run_paper_trade(redis, leader):
    config = DemoConfig.from_env()
    if config.status != "CONFIGURED":
        return
    client = DemoClient(config)
    try:
        while True:
            try:
                await PaperRuntime(redis, client, leader).run()
            except Exception:
                logger.warning("Binance Demo runtime stopped unexpectedly; reconnecting")
                await asyncio.sleep(10)
    finally:
        await client.close()
