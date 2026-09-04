"""Explicit one-time/reference-data seed helpers."""

from __future__ import annotations

from finance_analysis.core.time import utc_now


def seed_quant_reference_data(db_manager=None) -> dict:
    """Idempotently seed model definitions and unified universe definitions."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from finance_analysis.database.models.quant import ModelDefinition
    from finance_analysis.database.models.universe import Universe, UniverseInclude
    from finance_analysis.database.session import DatabaseManager
    from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES

    manager = db_manager or DatabaseManager.get_instance()
    with manager.session_scope() as session:
        definitions = [
            ("market_regime_rules", "Market regime rules", "market_regime", "classification"),
            ("time_series_logistic", "Shared panel logistic baseline", "time_series", "classification"),
            ("time_series_lgbm", "Shared panel LightGBM", "time_series", "regression"),
            ("cross_section_ridge", "Cross-sectional Ridge baseline", "cross_section", "regression"),
            ("cross_section_lgbm", "Qlib Alpha158 LightGBM", "cross_section", "regression"),
            ("signal_fusion", "Versioned signal fusion", "fusion", "ranking"),
        ]
        for key, name, model_type, task_type in definitions:
            values = dict(
                key=key,
                name=name,
                model_type=model_type,
                task_type=task_type,
                frequency="day",
                enabled=True,
                target_definition={"entry": "T+1 open", "exit": "T+5 close", "unit": "percentage_points"},
                default_config={},
                supported_markets=["US", "CN"],
            )
            session.execute(
                pg_insert(ModelDefinition)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[ModelDefinition.key],
                    set_={"supported_markets": values["supported_markets"], "updated_at": utc_now()},
                )
            )
        universe_values = (
            ("cn_all_a", "全部A股", "CN", "MARKET"),
            ("cn_csi300", "沪深300", "CN", "INDEX"),
            ("cn_csi500", "中证500", "CN", "INDEX"),
            ("cn_csi1000", "中证1000", "CN", "INDEX"),
            ("us_sp500", "S&P 500", "US", "INDEX"),
            ("cn_trend", "A股趋势跟踪", "CN", "STRATEGY"),
            ("us_trend", "美股趋势跟踪", "US", "STRATEGY"),
            ("cn_etf_rotation", "A股ETF轮动", "CN", "STRATEGY"),
            ("us_etf_rotation", "美股ETF轮动", "US", "STRATEGY"),
            (DEFAULT_QUANT_UNIVERSES["CN"], "A股量化", "CN", "STRATEGY"),
            (DEFAULT_QUANT_UNIVERSES["US"], "美股量化", "US", "STRATEGY"),
        )
        for key, name, market, universe_type in universe_values:
            values = {
                "key": key,
                "name": name,
                "market": market,
                "universe_type": universe_type,
                "enabled": True,
                "config": {},
            }
            session.execute(
                pg_insert(Universe)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[Universe.key],
                    set_={key: value for key, value in values.items() if key != "key"},
                )
            )
        universe_ids = dict(session.execute(select(Universe.key, Universe.id)).all())
        for parent, child in (
            ("cn_trend", "cn_all_a"),
            (DEFAULT_QUANT_UNIVERSES["CN"], "cn_csi300"),
            (DEFAULT_QUANT_UNIVERSES["US"], "us_sp500"),
        ):
            session.execute(
                pg_insert(UniverseInclude)
                .values(universe_id=universe_ids[parent], included_universe_id=universe_ids[child])
                .on_conflict_do_nothing(constraint="uix_universe_include")
            )
    return {
        "universes": [key for key, *_ in universe_values],
        "model_definitions": [key for key, *_ in definitions],
    }
