"""Explicit one-time/reference-data seed helpers."""

from __future__ import annotations

from finance_analysis.core.time import utc_now


def seed_quant_reference_data(db_manager=None) -> dict:
    """Idempotently seed model definitions and unified universe definitions."""
    from sqlalchemy import delete, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from finance_analysis.database.index_etf import seed_index_etf_universes

    from finance_analysis.database.models.quant import ModelDefinition
    from finance_analysis.database.models.universe import Universe, UniverseInclude
    from finance_analysis.database.session import DatabaseManager
    from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES

    manager = db_manager or DatabaseManager.get_instance()
    with manager.session_scope() as session:
        seed_index_etf_universes(session.connection())
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
            ("cn_csi2000", "中证2000", "CN", "INDEX"),
            ("us_sp500", "S&P 500", "US", "INDEX"),
            ("us_nasdaq100", "Nasdaq 100", "US", "INDEX"),
            ("cn_daily_sync", "A股日线同步", "CN", "STRATEGY"),
            ("us_daily_sync", "美股日线同步", "US", "STRATEGY"),
            ("cn_trend", "A股趋势跟踪", "CN", "STRATEGY"),
            ("us_trend", "美股趋势跟踪", "US", "STRATEGY"),
            ("cn_index_etf", "CN Index ETF", "CN", "STRATEGY"),
            ("us_index_etf", "US Index ETF", "US", "STRATEGY"),
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
        universe_ids = dict(
            session.execute(
                select(Universe.key, Universe.id).where(
                    Universe.key.in_([key for key, *_ in universe_values])
                )
            ).all()
        )

        session.execute(
            delete(UniverseInclude).where(
                UniverseInclude.universe_id.in_(
                    [universe_ids[key] for key in ("cn_trend", "us_trend", "cn_daily_sync", "us_daily_sync")]
                )
            )
        )
        for parent, child in (
            ("cn_daily_sync", "cn_csi300"),
            ("cn_daily_sync", "cn_csi500"),
            ("cn_daily_sync", "cn_csi1000"),
            ("cn_daily_sync", "cn_index_etf"),
            ("us_daily_sync", "us_sp500"),
            ("us_daily_sync", "us_index_etf"),
            ("cn_trend", "cn_csi300"),
            ("cn_trend", "cn_csi500"),
            ("cn_trend", "cn_csi1000"),
            ("cn_trend", "cn_csi2000"),
            ("us_trend", "us_sp500"),
        ):
            session.execute(
                pg_insert(UniverseInclude)
                .values(universe_id=universe_ids[parent], included_universe_id=universe_ids[child])
                .on_conflict_do_nothing(
                    index_elements=[UniverseInclude.universe_id, UniverseInclude.included_universe_id]
                )
            )
    return {
        "universes": [key for key, *_ in universe_values],
        "model_definitions": [key for key, *_ in definitions],
    }
