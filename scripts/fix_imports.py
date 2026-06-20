#!/usr/bin/env python3
"""Safely update imports and quoted module paths after package restructure."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {".py", ".sh", ".yml", ".yaml", ".md", ".toml", ".ini", ".env.example"}
SKIP_DIRS = {".git", ".venv", "node_modules", "static", "dist", "build", "__pycache__", ".pytest_cache"}

MODULE_REPLACEMENTS: list[tuple[str, str]] = [
    ("src.celery_app.tasks", "finance_analysis.tasks.celery.jobs"),
    ("src.celery_app.app", "finance_analysis.tasks.celery.app"),
    ("src.celery_app", "finance_analysis.tasks.celery"),
    ("src.notification_sender.telegram_sender", "finance_analysis.notification.senders.telegram"),
    ("src.notification_sender.ntfy_sender", "finance_analysis.notification.senders.ntfy"),
    ("src.notification_sender.email_sender", "finance_analysis.notification.senders.email"),
    ("src.notification_sender.astrbot_sender", "finance_analysis.notification.senders.astrbot"),
    ("src.notification_sender.custom_webhook_sender", "finance_analysis.notification.senders.custom_webhook"),
    ("src.notification_sender", "finance_analysis.notification.senders"),
    ("src.services.tasks.us_intraday_analysis", "finance_analysis.tasks.jobs.us_intraday_analysis"),
    ("src.services.tasks.us_premarket_news", "finance_analysis.tasks.jobs.us_premarket_news"),
    ("src.services.tasks.market_calendar_sync", "finance_analysis.tasks.jobs.market_calendar_sync"),
    ("src.services.history_comparison_service", "finance_analysis.analysis.history.comparison"),
    ("src.services.history_loader", "finance_analysis.analysis.history.loader"),
    ("src.services.history_service", "finance_analysis.analysis.history.service"),
    ("src.services.analysis_service", "finance_analysis.analysis.service"),
    ("src.services.agent_model_service", "finance_analysis.llm.model_service"),
    ("src.services.notification_diagnostics", "finance_analysis.notification.diagnostics"),
    ("src.services.social_sentiment_service", "finance_analysis.market_intelligence.social_sentiment"),
    ("src.services.report_renderer", "finance_analysis.reporting.template_renderer"),
    ("src.services.name_to_code_resolver", "finance_analysis.stocks.resolver"),
    ("src.services.market_type_utils", "finance_analysis.stocks.markets"),
    ("src.services.stock_code_utils", "finance_analysis.stocks.symbols"),
    ("src.services.import_parser", "finance_analysis.stock_lists.importer"),
    ("src.services.backtest_service", "finance_analysis.backtest.service"),
    ("src.services.stock_service", "finance_analysis.stocks.service"),
    ("src.services.task_center", "finance_analysis.tasks.service"),
    ("src.repositories.task_record_repo", "finance_analysis.database.repositories.task_record"),
    ("src.repositories.watch_list_repo", "finance_analysis.database.repositories.watch_list"),
    ("src.repositories.market_calendar_event_repo", "finance_analysis.database.repositories.market_calendar_event"),
    ("src.repositories.stock_list_repo", "finance_analysis.database.repositories.stock_list"),
    ("src.repositories.calendar_repo", "finance_analysis.database.repositories.calendar"),
    ("src.repositories.backtest_repo", "finance_analysis.database.repositories.backtest"),
    ("src.repositories.analysis_repo", "finance_analysis.database.repositories.analysis"),
    ("src.repositories.stock_repo", "finance_analysis.database.repositories.stock"),
    ("src.repositories.user_repo", "finance_analysis.database.repositories.user"),
    ("src.repositories", "finance_analysis.database.repositories"),
    ("src.core.pipeline_agent_result", "finance_analysis.analysis.pipeline_agent_result"),
    ("src.core.pipeline_config", "finance_analysis.analysis.pipeline_config"),
    ("src.core.pipeline", "finance_analysis.analysis.pipeline"),
    ("src.core.backtest_engine", "finance_analysis.backtest.engine"),
    ("src.core.market_review_runtime", "finance_analysis.market_review.runtime"),
    ("src.core.market_review_lock", "finance_analysis.market_review.lock"),
    ("src.core.market_review", "finance_analysis.market_review.service"),
    ("src.core.market_strategy", "finance_analysis.market_review.strategy"),
    ("src.core.market_profile", "finance_analysis.market_review.profile"),
    ("src.core.trading_calendar", "finance_analysis.market_review.trading_calendar"),
    ("src.core.config_registry", "finance_analysis.config.registry"),
    ("src.core.config_manager", "finance_analysis.config.loader"),
    ("src.utils.analysis_metadata", "finance_analysis.analysis.metadata"),
    ("src.utils.data_processing", "finance_analysis.analysis.context_normalizer"),
    ("src.utils.owner_uid", "finance_analysis.users.ownership"),
    ("src.utils.env", "finance_analysis.config.env_parsing"),
    ("src.db.conversation_repo", "finance_analysis.database.repositories.conversation"),
    ("src.db_migrations", "finance_analysis.database.migrations"),
    ("src.schemas.report_schema", "finance_analysis.reporting.schemas"),
    ("src.analysis.trend_analysis", "finance_analysis.analysis.technical.trend"),
    ("src.data.stock_index_loader", "finance_analysis.stocks.reference_data.loader"),
    ("src.data.stock_mapping", "finance_analysis.stocks.reference_data.mapping"),
    ("src.const.stock_index", "finance_analysis.stocks.reference_data.stock_index"),
    ("data_provider.longbridge_calendar_fetcher", "finance_analysis.integrations.market_data.providers.longbridge.calendar"),
    ("data_provider.longbridge_news_fetcher", "finance_analysis.integrations.market_data.providers.longbridge.news"),
    ("data_provider.longbridge_fetcher", "finance_analysis.integrations.market_data.providers.longbridge.market"),
    ("data_provider.yfinance_fetcher", "finance_analysis.integrations.market_data.providers.yfinance"),
    ("data_provider.tushare_fetcher", "finance_analysis.integrations.market_data.providers.tushare"),
    ("data_provider.tickflow_fetcher", "finance_analysis.integrations.market_data.providers.tickflow"),
    ("data_provider.pytdx_fetcher", "finance_analysis.integrations.market_data.providers.pytdx"),
    ("data_provider.efinance_fetcher", "finance_analysis.integrations.market_data.providers.efinance"),
    ("data_provider.baostock_fetcher", "finance_analysis.integrations.market_data.providers.baostock"),
    ("data_provider.akshare_fetcher", "finance_analysis.integrations.market_data.providers.akshare"),
    ("data_provider.us_index_mapping", "finance_analysis.integrations.market_data.providers.us_index_mapping"),
    ("data_provider", "finance_analysis.integrations.market_data"),
    ("src.notification_reports", "finance_analysis.reporting.markdown_renderer"),
    ("src.notification_routing", "finance_analysis.notification.routing"),
    ("src.notification_noise", "finance_analysis.notification.noise_control"),
    ("src.notification_config", "finance_analysis.notification.config"),
    ("src.report_config", "finance_analysis.reporting.config"),
    ("src.report_language", "finance_analysis.reporting.localization"),
    ("src.runtime_config", "finance_analysis.config.runtime"),
    ("src.logging_config", "finance_analysis.core.logging"),
    ("src.webui_frontend", "finance_analysis.core.frontend_assets"),
    ("src.search_service", "finance_analysis.search"),
    ("src.market_review_models", "finance_analysis.market_review.models"),
    ("src.market_analyzer", "finance_analysis.market_review.analyzer"),
    ("src.stock_analyzer", "finance_analysis.analysis.technical.analyzer"),
    ("src.market_context", "finance_analysis.analysis.market_context"),
    ("src.llm_client", "finance_analysis.llm.client"),
    ("src.time_utils", "finance_analysis.core.time"),
    ("src.scheduler", "finance_analysis.tasks.scheduler"),
    ("src.notification", "finance_analysis.notification.service"),
    ("src.storage", "finance_analysis.database"),
    ("src.models", "finance_analysis.database.models"),
    ("src.config", "finance_analysis.config"),
    ("src.tasks", "finance_analysis.tasks"),
    ("src.schemas", "finance_analysis.reporting.schemas"),
    ("src.analysis", "finance_analysis.analysis"),
    ("src.agent", "finance_analysis.agent"),
    ("src.search", "finance_analysis.search"),
    ("src.patches", "finance_analysis.patches"),
    ("src.llm", "finance_analysis.llm"),
    ("src.backtest", "finance_analysis.backtest"),
    ("src.db", "finance_analysis.database"),
    ("src.enums", "finance_analysis.reporting.types"),
    ("src.formatters", "finance_analysis.reporting.formatters"),
    ("src.md2img", "finance_analysis.reporting.md2img"),
    ("src.auth", "finance_analysis.users.auth"),
    ("src.core", "finance_analysis.core"),
    ("src.const", "finance_analysis.stocks.reference_data"),
    ("src.data", "finance_analysis.stocks.reference_data"),
    ("api.app", "finance_analysis.interfaces.api.app"),
    ("api.deps", "finance_analysis.interfaces.api.deps"),
    ("api.middlewares", "finance_analysis.interfaces.api.middlewares"),
    ("api.v1", "finance_analysis.interfaces.api.v1"),
    ("bot.commands", "finance_analysis.interfaces.bot.commands"),
    ("bot.platforms", "finance_analysis.interfaces.bot.platforms"),
    ("bot.dispatcher", "finance_analysis.interfaces.bot.dispatcher"),
    ("bot.handler", "finance_analysis.interfaces.bot.handler"),
    ("bot.models", "finance_analysis.interfaces.bot.models"),
    ("bot", "finance_analysis.interfaces.bot"),
    ("api", "finance_analysis.interfaces.api"),
    ("src", "finance_analysis"),
]

IMPORT_LINE = re.compile(
    r"^(\s*(?:from|import)\s+)([\w\.]+(?:\s*,\s*[\w\.]+)*)(\s*(?:import|,|\s).*)$",
    re.MULTILINE,
)
QUOTED_MODULE = re.compile(
    r"""(['"])((?:src|api|bot|data_provider)(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?::[A-Za-z_][A-Za-z0-9_]*)?)\1"""
)


def replace_modules(text: str) -> str:
    for old, new in MODULE_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def fix_import_lines(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        prefix, modules, suffix = match.group(1), match.group(2), match.group(3)
        parts = [replace_modules(part.strip()) for part in modules.split(",")]
        return prefix + ", ".join(parts) + suffix

    return IMPORT_LINE.sub(_sub, text)


def fix_quoted_modules(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        quote, module = match.group(1), match.group(2)
        return f"{quote}{replace_modules(module)}{quote}"

    return QUOTED_MODULE.sub(_sub, text)


def fix_patch_strings(text: str) -> str:
    return re.sub(
        r"""(patch|setattr|import_module)\((['"])([^'"]+)\2""",
        lambda m: f"{m.group(1)}({m.group(2)}{replace_modules(m.group(3))}{m.group(2)}",
        text,
    )


def should_process(path: Path) -> bool:
    if path.suffix not in TEXT_EXTENSIONS and path.name not in {"Dockerfile", "Dockerfile.dev"}:
        return False
    return not (SKIP_DIRS & set(path.parts))


def transform(text: str) -> str:
    text = fix_import_lines(text)
    text = fix_quoted_modules(text)
    text = fix_patch_strings(text)
    return text


def main() -> None:
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or not should_process(path):
            continue
        if path.name in {"fix_imports.py", "migrate_to_finance_analysis.py"}:
            continue
        original = path.read_text(encoding="utf-8")
        updated = transform(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    print(f"Updated {changed} files")


if __name__ == "__main__":
    main()
