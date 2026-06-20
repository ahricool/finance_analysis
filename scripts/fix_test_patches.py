#!/usr/bin/env python3
"""Bulk-update stale unittest.mock.patch targets after package restructure."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# patch string replacements (longest first)
PATCH_REPLACEMENTS: list[tuple[str, str]] = [
    ("finance_analysis.notification.service.get_config", "finance_analysis.notification.service.get_notification_config"),
    ("finance_analysis.analysis.stock_report_analyzer.get_config", "finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"),
    ("finance_analysis.analysis.technical.analyzer.get_config", "finance_analysis.reporting.config.get_report_config"),
    ("finance_analysis.market_review.analyzer.get_config", "finance_analysis.analysis.pipeline_config.get_pipeline_config"),
    ("finance_analysis.market_review.service.get_config", "finance_analysis.analysis.pipeline_config.get_pipeline_config"),
    ("finance_analysis.analysis.history.service.get_config", "finance_analysis.search.config.get_search_config"),
    ("finance_analysis.interfaces.api.v1.endpoints.agent.get_config", "finance_analysis.analysis.pipeline_config.get_pipeline_config"),
    ("finance_analysis.interfaces.bot.commands.research.get_config", "finance_analysis.analysis.pipeline_config.get_pipeline_config"),
    ("finance_analysis.interfaces.bot.commands.chat.get_config", "finance_analysis.analysis.pipeline_config.get_pipeline_config"),
    ("finance_analysis.agent.llm_adapter.get_config", "finance_analysis.llm.config.get_llm_config"),
    ("finance_analysis.database.session.get_config", "finance_analysis.database.config.get_database_config"),
    ("finance_analysis.integrations.market_data.providers.efinance.get_config", "finance_analysis.integrations.market_data.config.get_data_provider_config"),
    ("finance_analysis.integrations.market_data.providers.tushare.get_config", "finance_analysis.integrations.market_data.config.get_data_provider_config"),
    ("finance_analysis.config.get_config", "finance_analysis.config.runtime.get_runtime_config"),
    ("finance_analysis.notification.senders.astrfinance_analysis.interfaces.bot.requests.post", "finance_analysis.notification.senders.astrbot.requests.post"),
]

IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ("from fastapi import app as app_module", "from finance_analysis.interfaces import api as app_module"),
    ("import finance_analysis.webui_frontend", "import finance_analysis.core.frontend_assets"),
]


def transform_notification_test(text: str) -> str:
    if "test_notification.py" not in text and "TestNotification" not in text:
        return text
    # handled in dedicated file edit
    return text


def main() -> None:
    changed = 0
    for path in TESTS.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        new = text
        for old, val in PATCH_REPLACEMENTS:
            new = new.replace(old, val)
        for old, val in IMPORT_REPLACEMENTS:
            new = new.replace(old, val)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print("updated", path.relative_to(ROOT))
    print(f"done: {changed} files")


if __name__ == "__main__":
    main()
