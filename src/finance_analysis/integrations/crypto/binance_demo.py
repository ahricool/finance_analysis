"""Private USD-M Demo transport. No configurable host or write retries."""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

REST = "https://demo-fapi.binance.com"
WS = "wss://demo-fstream.binance.com"
# Explicit Demo-only method/path allowlist; absolute URL overrides are rejected.
READ_PATHS = frozenset(
    {
        "/fapi/v1/time",
        "/fapi/v3/account",
        "/fapi/v3/balance",
        "/fapi/v1/tradingSchedule",
        "/fapi/v3/positionRisk",
        "/fapi/v1/accountConfig",
        "/fapi/v1/symbolConfig",
        "/fapi/v1/exchangeInfo",
        "/fapi/v2/ticker/price",
        "/fapi/v1/premiumIndex",
        "/fapi/v1/openOrders",
        "/fapi/v1/openAlgoOrders",
        "/fapi/v1/allOrders",
        "/fapi/v1/allAlgoOrders",
        "/fapi/v1/userTrades",
        "/fapi/v1/income",
        "/fapi/v1/order",
        "/fapi/v1/algoOrder",
    }
)


class DemoError(Exception):
    def __init__(self, code, *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        # Never include exchange message, signed URL, credentials or listen key.
        super().__init__(f"Binance Demo error ({code})")


class _PrivateURLFilter(logging.Filter):
    def filter(self, record):
        return REST not in record.getMessage()


class DemoClient:
    def __init__(self, config, transport=None):
        self.secret = config.secret.encode()
        # HTTPX's INFO request logger includes signed query parameters.
        http_logger = logging.getLogger("httpx")
        if not any(isinstance(f, _PrivateURLFilter) for f in http_logger.filters):
            http_logger.addFilter(_PrivateURLFilter())
        self.http = httpx.AsyncClient(
            base_url=REST, transport=transport, timeout=10, headers={"X-MBX-APIKEY": config.key}, follow_redirects=False
        )
        self.offset = 0

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, params=None, *, signed=True):
        allowed = (
            (method == "GET" and path in READ_PATHS)
            or (method in {"POST", "DELETE"} and path in {"/fapi/v1/order", "/fapi/v1/algoOrder"})
            or (method in {"POST", "PUT"} and path == "/fapi/v1/listenKey")
        )
        if not allowed:
            raise DemoError("DEMO_ENDPOINT_NOT_ALLOWED")
        values = dict(params or {})
        if signed:
            values.update(timestamp=int(time.time() * 1000) + self.offset, recvWindow=5000)
            values["signature"] = hmac.new(self.secret, urlencode(values).encode(), hashlib.sha256).hexdigest()
        try:
            response = await self.http.request(method, path, params=values)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise DemoError("NETWORK", uncertain=method != "GET") from None
        code = response.status_code
        if isinstance(data, dict) and "code" in data:
            try:
                code = int(data["code"])
            except (ValueError, TypeError):
                pass
        if not response.is_success or code < 0:
            raise DemoError(
                code,
                uncertain=method != "GET"
                and (response.status_code >= 500 or response.status_code == 408 or code in {-1006, -1007}),
            )
        return data

    async def sync_clock(self):
        data = await self.request("GET", "/fapi/v1/time", signed=False)
        self.offset = int(data["serverTime"]) - int(time.time() * 1000)

    async def account(self):
        return await self.request("GET", "/fapi/v3/account")

    async def balances(self):
        return await self.request("GET", "/fapi/v3/balance")

    async def schedule(self):
        return await self.request("GET", "/fapi/v1/tradingSchedule", signed=False)

    async def positions(self):
        return await self.request("GET", "/fapi/v3/positionRisk")

    async def configuration(self):
        return await self.request("GET", "/fapi/v1/accountConfig")

    async def symbol_config(self):
        return await self.request("GET", "/fapi/v1/symbolConfig")

    async def rules(self):
        return (await self.request("GET", "/fapi/v1/exchangeInfo", signed=False))["symbols"]

    async def quote(self, symbol):
        return await self.request("GET", "/fapi/v2/ticker/price", {"symbol": symbol}, signed=False)

    async def funding(self, symbol):
        return await self.request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)

    async def open_orders(self, algo=False):
        return await self.request("GET", "/fapi/v1/openAlgoOrders" if algo else "/fapi/v1/openOrders")

    async def history(self, symbol, kind, **params):
        paths = {"order": "allOrders", "algo": "allAlgoOrders", "trade": "userTrades"}
        return await self.request("GET", "/fapi/v1/" + paths[kind], {"symbol": symbol, **params})

    async def income(self, **params):
        return await self.request("GET", "/fapi/v1/income", params)

    async def submit(self, params, algo=False):
        return await self.request("POST", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", params)

    async def query(self, symbol, client_id, algo=False):
        params = {"clientAlgoId": client_id} if algo else {"symbol": symbol, "origClientOrderId": client_id}
        return await self.request("GET", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", params)

    async def cancel(self, symbol, exchange_id, algo=False):
        params = {"algoId": exchange_id} if algo else {"symbol": symbol, "orderId": exchange_id}
        return await self.request("DELETE", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", params)

    async def listen(self, method="POST"):
        return await self.request(method, "/fapi/v1/listenKey", signed=False)
