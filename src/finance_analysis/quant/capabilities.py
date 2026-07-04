"""Honest runtime capability reporting; unavailable dependencies never fake results."""

from __future__ import annotations

import os
import sys


def get_quant_capabilities() -> dict:
    broker_configured = bool(os.getenv("REDIS_URL"))
    qlib = {
        "status": "configured" if broker_configured else "unavailable",
        "version": "0.9.7",
        "execution": "celery_queue",
        "queue": "qlib",
        "reason": None if broker_configured else "REDIS_URL is not configured",
    }
    return {
        "status": "available" if broker_configured else "degraded",
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "price_modes": ["raw"],
        "markets": {"US": "available", "HK": "data_dependent", "CN": "data_dependent"},
        "qlib": qlib,
        "lightgbm": "isolated_in_qlib_worker",
        "sklearn": "isolated_in_qlib_worker",
        "adjusted_prices": {
            "status": "unavailable",
            "reason": "stock_daily currently stores raw prices and no corporate-action factor",
        },
        "event_providers": {"manual_json_csv": "available", "llm_extraction": "disabled"},
        "warnings": ["当前使用未复权价格，公司行动可能影响长期模型和回测结果。"],
    }
