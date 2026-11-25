"""Production USD-M account reader.

An exact method/path allowlist excludes every trading and transfer operation.
POST/PUT are permitted ONLY for user-data listen-key lifecycle.
"""

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

REST = "https://fapi.binance.com"
WS = "wss://fstream.binance.com/private"
PUBLIC_READS = frozenset({"/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/premiumIndex"})
PRIVATE_READS = frozenset(
    {
        "/fapi/v3/account",
        "/fapi/v3/balance",
        "/fapi/v3/positionRisk",
        "/fapi/v1/accountConfig",
        "/fapi/v1/symbolConfig",
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
LISTEN = "/fapi/v1/listenKey"


class LiveReadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Binance Live read error ({code})")


class _SignedRequestFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not (REST in message and ("signature=" in message or LISTEN in message))


class LiveReader:
    def __init__(self, config, transport=None):
        self._secret = config.secret.encode()
        self._key = config.key
        self._offset = 0
        log = logging.getLogger("httpx")
        if not any(isinstance(f, _SignedRequestFilter) for f in log.filters):
            log.addFilter(_SignedRequestFilter())
        self._http = httpx.AsyncClient(base_url=REST, transport=transport, timeout=10, follow_redirects=False)

    async def close(self):
        await self._http.aclose()

    async def _request(self, method, path, params=None):
        signed = method == "GET" and path in PRIVATE_READS
        stream = path == LISTEN and method in {"POST", "PUT"}
        if not (signed or stream or (method == "GET" and path in PUBLIC_READS)):
            raise LiveReadError("READ_ONLY_TRANSPORT")
        values = dict(params or {})
        if signed:
            values.update(timestamp=int(time.time() * 1000) + self._offset, recvWindow=5000)
            values["signature"] = hmac.new(self._secret, urlencode(values).encode(), hashlib.sha256).hexdigest()
        try:
            response = await self._http.request(
                method,
                path,
                params=values,
                headers={"X-MBX-APIKEY": self._key} if signed or stream else {},
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise LiveReadError("NETWORK") from None
        code = response.status_code
        if isinstance(data, dict) and "code" in data:
            try:
                code = int(data["code"])
            except (TypeError, ValueError):
                pass
        if not response.is_success or code < 0:
            raise LiveReadError(code)
        return data

    async def sync_clock(self):
        data = await self._request("GET", "/fapi/v1/time")
        self._offset = int(data["serverTime"]) - int(time.time() * 1000)

    async def account(self):
        return await self._request("GET", "/fapi/v3/account")

    async def balances(self):
        return await self._request("GET", "/fapi/v3/balance")

    async def positions(self):
        return await self._request("GET", "/fapi/v3/positionRisk")

    async def configuration(self):
        return await self._request("GET", "/fapi/v1/accountConfig")

    async def symbol_config(self):
        return await self._request("GET", "/fapi/v1/symbolConfig")

    async def rules(self):
        return (await self._request("GET", "/fapi/v1/exchangeInfo"))["symbols"]

    async def funding(self, symbol):
        return await self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})

    async def open_orders(self, algo=False):
        return await self._request("GET", "/fapi/v1/openAlgoOrders" if algo else "/fapi/v1/openOrders")

    async def history(self, symbol, kind, **params):
        paths = {"order": "allOrders", "algo": "allAlgoOrders", "trade": "userTrades"}
        return await self._request("GET", "/fapi/v1/" + paths[kind], {"symbol": symbol, **params})

    async def income(self, **params):
        return await self._request("GET", "/fapi/v1/income", params)

    async def query(self, symbol, client_id, algo=False):
        params = {"clientAlgoId": client_id} if algo else {"symbol": symbol, "origClientOrderId": client_id}
        return await self._request("GET", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", params)

    async def listen(self, method="POST"):
        return await self._request(method, LISTEN)
