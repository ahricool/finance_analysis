"""Explicit read-only live probe. Never part of offline pytest; never prints credentials."""

import argparse
import json

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", help="Existing backend env file containing FUYAO_API_KEY")
    args = parser.parse_args()
    if args.env:
        key = dotenv_values(args.env).get("FUYAO_API_KEY")
    else:
        from finance_analysis.config import load_env
        from finance_analysis.integrations.market_data.config import get_data_provider_config

        load_env()
        key = get_data_provider_config().fuyao_api_key
    if not key:
        print("NOT VERIFIED: FUYAO_API_KEY not configured")
        return 2
    checks = [
        ("single", {"thscode": "510300.SH"}),
        ("plural_batch", {"thscodes": "510300.SH,510500.SH"}),
        ("singular_batch", {"thscode": "510300.SH,510500.SH"}),
    ]
    with httpx.Client(timeout=20) as client:
        for name, params in checks:
            response = client.get(
                "https://fuyao.aicubes.cn/api/fund/market/snapshot", params=params, headers={"X-api-key": key}
            )
            body = response.json()
            data = body.get("data") or {}
            print(
                json.dumps(
                    {
                        "check": name,
                        "http": response.status_code,
                        "code": body.get("code"),
                        "message": body.get("message"),
                        "symbols": [row.get("thscode") for row in data.get("item", [])],
                    },
                    ensure_ascii=False,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
