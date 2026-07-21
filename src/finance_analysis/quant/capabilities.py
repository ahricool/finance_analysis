"""Honest runtime capability reporting; unavailable dependencies never fake results."""

from __future__ import annotations

import os
import sys


def get_quant_capabilities(market: str = "US", repository=None) -> dict:
    from finance_analysis.database.repositories.quant import QuantRepository
    from finance_analysis.quant.markets import get_quant_market_config

    market_config = get_quant_market_config(market)
    repository = repository or QuantRepository()
    broker_configured = bool(os.getenv("REDIS_URL"))
    qlib = {
        "status": "configured" if broker_configured else "unavailable",
        "version": "0.9.7",
        "execution": "celery_queue",
        "queue": "qlib",
        "reason": None if broker_configured else "REDIS_URL is not configured",
    }
    required_models = ("cross_section_lgbm", "time_series_lgbm")
    model_status = {
        key: "production" if repository.production_model(market_config.market, key) else "unavailable"
        for key in required_models
    }
    models_ready = all(value == "production" for value in model_status.values())
    warnings = ["当前使用未复权价格，公司行动可能影响长期模型和回测结果。"]
    if not models_ready:
        warnings.append(f"{market_config.market} production 模型尚未就绪。")
    return {
        "status": "available" if broker_configured and models_ready else "degraded",
        "market": market_config.market,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "price_modes": ["raw"],
        "markets": {"US": "available", "CN": "available"},
        "models": {"status": "available" if models_ready else "unavailable", "required": model_status},
        "qlib": qlib,
        "lightgbm": "isolated_in_qlib_worker",
        "sklearn": "isolated_in_qlib_worker",
        "adjusted_prices": {
            "status": "unavailable",
            "reason": "stock_daily currently stores raw prices and no corporate-action factor",
        },
        "event_providers": {"manual_json_csv": "available", "llm_extraction": "disabled"},
        "warnings": warnings,
    }
