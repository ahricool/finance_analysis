"""Manual, read-only public-feed comparison; never run as part of offline pytest.

Usage: uv run python scripts/check_cn_minute_sources.py --rounds 3 --qps 2
Production network: docker exec -i finance-analysis-server python - < scripts/check_cn_minute_sources.py
No API key, business database, or Redis writes are needed.
"""

import argparse
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import median
from threading import Lock
from time import monotonic, sleep

import requests

SOURCES = ("sina", "eastmoney", "tencent_m1", "easyquotation_timekline")
DEFAULT_SYMBOLS = ("600000.SH", "000001.SZ", "688001.SH", "510300.SH", "000001.SH", "920002.BJ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--qps", type=float, default=1)
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()
    if args.rounds < 1 or not 0 < args.qps <= 2:
        parser.error("rounds must be positive; diagnostic aggregate qps must be in (0, 2]")
    lock, next_start = Lock(), [0.0]

    def probe(task):
        source, symbol = task
        with lock:
            delay = max(0, next_start[0] - monotonic())
            next_start[0] = max(next_start[0], monotonic()) + 1 / args.qps
        sleep(delay)
        started = monotonic()
        result = {"source": source, "symbol": symbol}
        try:
            code, exchange = symbol.split(".")
            prefixed = exchange.lower() + code
            if source == "sina":
                r = requests.get(
                    "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData",
                    params={"symbol": prefixed, "scale": "1", "ma": "no", "datalen": "320"},
                    timeout=8,
                )
                r.raise_for_status()
                rows = json.loads(r.text.split("=(", 1)[1].rsplit(");", 1)[0]) or []
                result["latest_label"] = rows[-1]["day"] if rows else None
                result["ohlc"] = True
            elif source == "eastmoney":
                r = requests.get(
                    "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
                    params={
                        "secid": ("1" if exchange == "SH" else "0") + "." + code,
                        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                        "iscr": "0",
                        "ndays": "1",
                    },
                    timeout=8,
                )
                r.raise_for_status()
                rows = (r.json().get("data") or {}).get("trends") or []
                result["latest_label"] = rows[-1].split(",")[0] if rows else None
                result["ohlc"] = True
            elif source == "tencent_m1":
                r = requests.get(
                    "https://ifzq.gtimg.cn/appstock/app/kline/mkline",
                    params={"param": f"{prefixed},m1,,320"},
                    timeout=8,
                )
                r.raise_for_status()
                rows = (r.json().get("data", {}).get(prefixed) or {}).get("m1") or []
                result["latest_label"] = rows[-1][0] if rows else None
                result["ohlc"] = True
            else:
                r = requests.get(f"https://data.gtimg.cn/flashdata/hushen/minute/{prefixed}.js", timeout=8)
                r.raise_for_status()
                rows = re.findall(r"\d{4} [0-9.]+ [0-9.]+", r.text)
                # Detect old static files rather than counting HTTP 200 as usable live OHLC.
                result["response_date"] = r.text.split("date:", 1)[-1][:6]
                result["ohlc"] = False
            result.update(status=r.status_code, rows=len(rows))
        except Exception as exc:
            result["error"] = type(exc).__name__
        result["seconds"] = round(monotonic() - started, 3)
        return result

    print(
        json.dumps(
            {
                "started": datetime.now(timezone.utc).isoformat(),
                "aggregate_qps_cap": args.qps,
                "workers": 3,
                "rounds": args.rounds,
            }
        ),
        flush=True,
    )
    tasks = [(source, symbol) for _ in range(args.rounds) for source in SOURCES for symbol in args.symbols]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, tasks))
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    for source in SOURCES:
        selected = [r for r in results if r["source"] == source]
        successful = [r for r in selected if r.get("status") == 200]
        latency = sorted(r["seconds"] for r in successful)
        print(
            json.dumps(
                {
                    "source": source,
                    "requests": len(selected),
                    "http_ok": len(successful),
                    "nonempty": sum(bool(r.get("rows")) for r in selected),
                    "success_p50_seconds": median(latency) if latency else None,
                    "success_p95_seconds": latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
                }
            )
        )


if __name__ == "__main__":
    main()
