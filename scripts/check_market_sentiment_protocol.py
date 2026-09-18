"""Opt-in live REST protocol check; writes data under DATA_DIR/tmp, never to the browser.

Run: uv run python scripts/check_market_sentiment_protocol.py
This is not a pytest and is never run by the offline CI gate.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder
from finance_analysis.config import load_env
from finance_analysis.core.paths import get_temp_dir
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider, FuyaoError, date_ms
from finance_analysis.integrations.market_data.request_budget import request_budget
from finance_analysis.market_sentiment.calendar import expected_date, sessions_through


def main():
    load_env()
    provider = FuyaoProvider()
    if not provider._api_key:
        print("NOT VERIFIED: backend FUYAO_API_KEY is not configured; no requests made")
        return 2
    directory = get_temp_dir() / ("sentiment-protocol-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir(parents=True, exist_ok=False)
    days = sessions_through(expected_date(), 2)
    results = []
    checks = [
        (
            "small_page",
            lambda: provider._get(
                "/api/a-share/special-data/limit-up-pool",
                date_ms=date_ms(days[-1]),
                page=1,
                size=2,
                sort_field="continue_day_cnt",
                sort_dir="desc",
            ),
        )
    ]
    checks += [("limit_up_" + str(day), lambda day=day: asdict(provider.get_limit_up_pool(day))) for day in days]
    checks += [
        ("ladder", lambda: asdict(provider.get_limit_up_ladder())),
        ("limit_down", lambda: asdict(provider.get_limit_down_pool(days[-1]))),
        ("limit_break", lambda: asdict(provider.get_limit_break_pool(days[-1]))),
    ]
    for name, fetch in checks:
        try:
            with request_budget(120):
                data = fetch()
            (directory / f"{name}.json").write_text(
                json.dumps(jsonable_encoder(data), ensure_ascii=False), encoding="utf-8"
            )
            items = data.get("items", data.get("item", []))
            result = {
                "check": name,
                "status": "verified",
                "rows": len(items),
                "source_timestamp": jsonable_encoder(data.get("source_timestamp", data.get("timestamp"))),
                "pagination": data.get("pagination"),
                "window": data.get("window"),
            }
            if name.startswith("limit_up_"):
                result["continuity_pairs"] = sorted(
                    {(str(r.get("continue_day_cnt")), str(r.get("continue_day_text"))) for r in items}
                )
            results.append(result)
        except (FuyaoError, TimeoutError) as exc:
            results.append({"check": name, "status": "failed", "error": str(exc)})
    (directory / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(directory), "results": results}, ensure_ascii=False, indent=2))
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
