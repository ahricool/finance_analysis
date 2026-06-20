#!/usr/bin/env python3
"""One-shot migration script: move Python packages to src/finance_analysis/."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FA = SRC / "finance_analysis"


def git_mv(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        print(f"SKIP missing: {src}")
        return
    if dst.exists():
        print(f"SKIP exists: {dst}")
        return
    result = subprocess.run(["git", "mv", str(src), str(dst)], cwd=ROOT, check=False)
    if result.returncode == 0:
        print(f"mv {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
        return
    # Fallback for cross-device or directory moves
    if src.is_dir():
        shutil.copytree(src, dst)
        subprocess.run(["git", "add", str(dst)], cwd=ROOT, check=True)
        subprocess.run(["git", "rm", "-r", str(src)], cwd=ROOT, check=True)
    else:
        shutil.copy2(src, dst)
        subprocess.run(["git", "add", str(dst)], cwd=ROOT, check=True)
        subprocess.run(["git", "rm", str(src)], cwd=ROOT, check=True)
    print(f"mv(fallback) {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")


def mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def touch_init(path: Path) -> None:
    init = path / "__init__.py"
    if not init.exists():
        init.write_text('"""Package."""\n', encoding="utf-8")


# Phase 1: create top-level package skeleton
mkdir(FA)
touch_init(FA)

MOVES: list[tuple[str, str]] = [
    # core
    ("src/logging_config.py", "src/finance_analysis/core/logging.py"),
    ("src/time_utils.py", "src/finance_analysis/core/time.py"),
    ("src/webui_frontend.py", "src/finance_analysis/core/frontend_assets.py"),
    # config pieces (existing split modules)
    ("src/runtime_config.py", "src/finance_analysis/config/runtime.py"),
    ("src/core/config_manager.py", "src/finance_analysis/config/loader.py"),
    ("src/core/config_registry.py", "src/finance_analysis/config/registry.py"),
    ("src/utils/env.py", "src/finance_analysis/config/env_parsing.py"),
    # database
    ("src/db/base.py", "src/finance_analysis/database/base.py"),
    ("src/db/config.py", "src/finance_analysis/database/config.py"),
    ("src/db/session.py", "src/finance_analysis/database/session.py"),
    ("src/db/bootstrap.py", "src/finance_analysis/database/bootstrap.py"),
    ("src/db_migrations.py", "src/finance_analysis/database/migrations.py"),
    ("src/db/conversation_repo.py", "src/finance_analysis/database/repositories/conversation.py"),
    # users
    ("src/auth.py", "src/finance_analysis/users/auth.py"),
    ("src/utils/owner_uid.py", "src/finance_analysis/users/ownership.py"),
    # stocks
    ("src/services/stock_service.py", "src/finance_analysis/stocks/service.py"),
    ("src/services/stock_code_utils.py", "src/finance_analysis/stocks/symbols.py"),
    ("src/services/market_type_utils.py", "src/finance_analysis/stocks/markets.py"),
    ("src/services/name_to_code_resolver.py", "src/finance_analysis/stocks/resolver.py"),
    ("src/const/stock_index.py", "src/finance_analysis/stocks/reference_data/stock_index.py"),
    ("src/data/stock_index_loader.py", "src/finance_analysis/stocks/reference_data/loader.py"),
    ("src/data/stock_mapping.py", "src/finance_analysis/stocks/reference_data/mapping.py"),
    # stock_lists
    ("src/services/import_parser.py", "src/finance_analysis/stock_lists/importer.py"),
    # analysis pipeline
    ("src/core/pipeline.py", "src/finance_analysis/analysis/pipeline.py"),
    ("src/core/pipeline_agent_result.py", "src/finance_analysis/analysis/pipeline_agent_result.py"),
    ("src/core/pipeline_config.py", "src/finance_analysis/analysis/pipeline_config.py"),
    ("src/stock_analyzer.py", "src/finance_analysis/analysis/technical/analyzer.py"),
    ("src/utils/analysis_metadata.py", "src/finance_analysis/analysis/metadata.py"),
    ("src/utils/data_processing.py", "src/finance_analysis/analysis/context_normalizer.py"),
    ("src/market_context.py", "src/finance_analysis/analysis/market_context.py"),
    # backtest
    ("src/core/backtest_engine.py", "src/finance_analysis/backtest/engine.py"),
    ("src/services/backtest_service.py", "src/finance_analysis/backtest/service.py"),
    ("src/backtest/config.py", "src/finance_analysis/backtest/config.py"),
    # market_review
    ("src/market_analyzer.py", "src/finance_analysis/market_review/analyzer.py"),
    ("src/market_review_models.py", "src/finance_analysis/market_review/models.py"),
    ("src/core/market_review.py", "src/finance_analysis/market_review/service.py"),
    ("src/core/market_review_runtime.py", "src/finance_analysis/market_review/runtime.py"),
    ("src/core/market_review_lock.py", "src/finance_analysis/market_review/lock.py"),
    ("src/core/market_profile.py", "src/finance_analysis/market_review/profile.py"),
    ("src/core/market_strategy.py", "src/finance_analysis/market_review/strategy.py"),
    ("src/core/trading_calendar.py", "src/finance_analysis/market_review/trading_calendar.py"),
    # market_intelligence
    ("src/services/social_sentiment_service.py", "src/finance_analysis/market_intelligence/social_sentiment.py"),
    # reporting
    ("src/notification_reports.py", "src/finance_analysis/reporting/markdown_renderer.py"),
    ("src/services/report_renderer.py", "src/finance_analysis/reporting/template_renderer.py"),
    ("src/report_language.py", "src/finance_analysis/reporting/localization.py"),
    ("src/schemas/report_schema.py", "src/finance_analysis/reporting/schemas.py"),
    ("src/enums.py", "src/finance_analysis/reporting/types.py"),
    ("src/formatters.py", "src/finance_analysis/reporting/formatters.py"),
    ("src/md2img.py", "src/finance_analysis/reporting/md2img.py"),
    ("src/report_config.py", "src/finance_analysis/reporting/config.py"),
    # notification
    ("src/notification.py", "src/finance_analysis/notification/service.py"),
    ("src/notification_routing.py", "src/finance_analysis/notification/routing.py"),
    ("src/notification_noise.py", "src/finance_analysis/notification/noise_control.py"),
    ("src/services/notification_diagnostics.py", "src/finance_analysis/notification/diagnostics.py"),
    ("src/notification_config.py", "src/finance_analysis/notification/config.py"),
    # llm
    ("src/llm/client.py", "src/finance_analysis/llm/client.py"),
    ("src/llm/config.py", "src/finance_analysis/llm/config.py"),
    ("src/llm/types.py", "src/finance_analysis/llm/types.py"),
    # tasks
    ("src/scheduler.py", "src/finance_analysis/tasks/scheduler.py"),
    ("src/services/task_center.py", "src/finance_analysis/tasks/service.py"),
    ("src/tasks/bot_payload.py", "src/finance_analysis/tasks/payloads.py"),
    ("src/tasks/lifecycle.py", "src/finance_analysis/tasks/lifecycle.py"),
    ("src/tasks/queue.py", "src/finance_analysis/tasks/queue.py"),
    ("src/celery_app/app.py", "src/finance_analysis/tasks/celery/app.py"),
    ("src/services/analysis_service.py", "src/finance_analysis/analysis/service.py"),
    ("src/services/history_service.py", "src/finance_analysis/analysis/history/service.py"),
    ("src/services/history_loader.py", "src/finance_analysis/analysis/history/loader.py"),
    ("src/services/history_comparison_service.py", "src/finance_analysis/analysis/history/comparison.py"),
    ("src/services/agent_model_service.py", "src/finance_analysis/llm/model_service.py"),
]

# Whole directories moved with git mv
DIR_MOVES: list[tuple[str, str]] = [
    ("src/agent", "src/finance_analysis/agent"),
    ("src/search", "src/finance_analysis/search"),
    ("src/patches", "src/finance_analysis/patches"),
    ("src/models", "src/finance_analysis/database/models"),
    ("api", "src/finance_analysis/interfaces/api"),
    ("bot", "src/finance_analysis/interfaces/bot"),
    ("data_provider", "src/finance_analysis/integrations/market_data"),
    ("src/services/tasks/market_calendar_sync", "src/finance_analysis/tasks/jobs/market_calendar_sync"),
    ("src/services/tasks/us_premarket_news", "src/finance_analysis/tasks/jobs/us_premarket_news"),
    ("src/services/tasks/us_intraday_analysis", "src/finance_analysis/tasks/jobs/us_intraday_analysis"),
    ("src/celery_app/tasks", "src/finance_analysis/tasks/celery/jobs"),
]

REPO_RENAMES: list[tuple[str, str]] = [
    ("src/finance_analysis/database/repositories/analysis_repo.py", "src/finance_analysis/database/repositories/analysis.py"),
    ("src/finance_analysis/database/repositories/backtest_repo.py", "src/finance_analysis/database/repositories/backtest.py"),
    ("src/finance_analysis/database/repositories/calendar_repo.py", "src/finance_analysis/database/repositories/calendar.py"),
    ("src/finance_analysis/database/repositories/market_calendar_event_repo.py", "src/finance_analysis/database/repositories/market_calendar_event.py"),
    ("src/finance_analysis/database/repositories/stock_list_repo.py", "src/finance_analysis/database/repositories/stock_list.py"),
    ("src/finance_analysis/database/repositories/stock_repo.py", "src/finance_analysis/database/repositories/stock.py"),
    ("src/finance_analysis/database/repositories/task_record_repo.py", "src/finance_analysis/database/repositories/task_record.py"),
    ("src/finance_analysis/database/repositories/user_repo.py", "src/finance_analysis/database/repositories/user.py"),
    ("src/finance_analysis/database/repositories/watch_list_repo.py", "src/finance_analysis/database/repositories/watch_list.py"),
    ("src/finance_analysis/notification/senders/telegram_sender.py", "src/finance_analysis/notification/senders/telegram.py"),
    ("src/finance_analysis/notification/senders/ntfy_sender.py", "src/finance_analysis/notification/senders/ntfy.py"),
    ("src/finance_analysis/notification/senders/email_sender.py", "src/finance_analysis/notification/senders/email.py"),
    ("src/finance_analysis/notification/senders/astrbot_sender.py", "src/finance_analysis/notification/senders/astrbot.py"),
    ("src/finance_analysis/notification/senders/custom_webhook_sender.py", "src/finance_analysis/notification/senders/custom_webhook.py"),
    ("src/finance_analysis/integrations/market_data/longbridge_fetcher.py", "src/finance_analysis/integrations/market_data/providers/longbridge/market.py"),
    ("src/finance_analysis/integrations/market_data/longbridge_news_fetcher.py", "src/finance_analysis/integrations/market_data/providers/longbridge/news.py"),
    ("src/finance_analysis/integrations/market_data/longbridge_calendar_fetcher.py", "src/finance_analysis/integrations/market_data/providers/longbridge/calendar.py"),
    ("src/finance_analysis/integrations/market_data/akshare_fetcher.py", "src/finance_analysis/integrations/market_data/providers/akshare.py"),
    ("src/finance_analysis/integrations/market_data/baostock_fetcher.py", "src/finance_analysis/integrations/market_data/providers/baostock.py"),
    ("src/finance_analysis/integrations/market_data/efinance_fetcher.py", "src/finance_analysis/integrations/market_data/providers/efinance.py"),
    ("src/finance_analysis/integrations/market_data/pytdx_fetcher.py", "src/finance_analysis/integrations/market_data/providers/pytdx.py"),
    ("src/finance_analysis/integrations/market_data/tickflow_fetcher.py", "src/finance_analysis/integrations/market_data/providers/tickflow.py"),
    ("src/finance_analysis/integrations/market_data/tushare_fetcher.py", "src/finance_analysis/integrations/market_data/providers/tushare.py"),
    ("src/finance_analysis/integrations/market_data/yfinance_fetcher.py", "src/finance_analysis/integrations/market_data/providers/yfinance.py"),
    ("src/finance_analysis/integrations/market_data/us_index_mapping.py", "src/finance_analysis/integrations/market_data/providers/us_index_mapping.py"),
]


def move_repositories() -> None:
    repos = ROOT / "src/repositories"
    if not repos.exists():
        return
    dst_dir = FA / "database" / "repositories"
    mkdir(dst_dir)
    for item in sorted(repos.glob("*.py")):
        if item.name == "__init__.py":
            git_mv(item, dst_dir / item.name)
        else:
            new_name = item.name.replace("_repo.py", ".py")
            git_mv(item, dst_dir / new_name)


def move_notification_senders() -> None:
    src_dir = ROOT / "src/notification_sender"
    if not src_dir.exists():
        return
    dst_dir = FA / "notification" / "senders"
    mkdir(dst_dir)
    rename_map = {
        "telegram_sender.py": "telegram.py",
        "ntfy_sender.py": "ntfy.py",
        "email_sender.py": "email.py",
        "astrbot_sender.py": "astrbot.py",
        "custom_webhook_sender.py": "custom_webhook.py",
    }
    for item in sorted(src_dir.iterdir()):
        if item.name == "__init__.py":
            git_mv(item, dst_dir / item.name)
        elif item.suffix == ".py":
            git_mv(item, dst_dir / rename_map.get(item.name, item.name))


def move_analysis_package() -> None:
    src_dir = ROOT / "src/analysis"
    dst_dir = FA / "analysis"
    if not src_dir.exists():
        return
    mkdir(dst_dir)
    for item in sorted(src_dir.iterdir()):
        if item.name == "__pycache__":
            continue
        if item.name == "trend_analysis.py":
            git_mv(item, dst_dir / "technical" / "trend.py")
        else:
            git_mv(item, dst_dir / item.name)


def merge_analysis_dir() -> None:
    pass


def restore_config_from_git() -> None:
    cfg = FA / "config"
    mkdir(cfg)
    commit = "ff7a019^"
    files = ["model.py", "constants.py", "news.py", "agent_models.py"]
    for name in files:
        dst = cfg / name
        if dst.exists():
            continue
        result = subprocess.run(
            ["git", "show", f"{commit}:src/config/{name}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"WARN could not restore config/{name}")
            continue
        dst.write_text(result.stdout, encoding="utf-8")
        subprocess.run(["git", "add", str(dst)], cwd=ROOT, check=True)
        print(f"restored config/{name} from git")


def main() -> None:
    os.chdir(ROOT)
    for rel_src, rel_dst in MOVES:
        git_mv(ROOT / rel_src, ROOT / rel_dst)

    for rel_src, rel_dst in DIR_MOVES:
        src = ROOT / rel_src
        dst = ROOT / rel_dst
        if src.exists():
            git_mv(src, dst)

    move_repositories()
    move_notification_senders()
    move_analysis_package()

    for rel_src, rel_dst in REPO_RENAMES:
        git_mv(ROOT / rel_src, ROOT / rel_dst)

    merge_analysis_dir()
    restore_config_from_git()
    for path in [
        FA / "core",
        FA / "config",
        FA / "database",
        FA / "database/models",
        FA / "database/repositories",
        FA / "users",
        FA / "stocks",
        FA / "stocks/reference_data",
        FA / "stock_lists",
        FA / "analysis",
        FA / "analysis/technical",
        FA / "analysis/history",
        FA / "backtest",
        FA / "market_review",
        FA / "market_intelligence",
        FA / "reporting",
        FA / "notification",
        FA / "notification/senders",
        FA / "llm",
        FA / "tasks",
        FA / "tasks/celery",
        FA / "tasks/celery/jobs",
        FA / "tasks/jobs",
        FA / "integrations",
        FA / "integrations/market_data",
        FA / "integrations/market_data/providers",
        FA / "integrations/market_data/providers/longbridge",
        FA / "interfaces",
        FA / "interfaces/api",
        FA / "interfaces/bot",
    ]:
        touch_init(path)

    print("Migration file moves complete.")


if __name__ == "__main__":
    main()
