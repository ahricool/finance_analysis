"""Structural guarantees for the explicit Celery task layout."""

from __future__ import annotations

import importlib
from pathlib import Path

from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.jobs import TASK_MODULES, TASK_PACKAGES
from finance_analysis.tasks.celery.metadata import ON_DEMAND_TASKS
from finance_analysis.tasks.celery.schedule import get_scheduled_task_definitions
from finance_analysis.tasks.lifecycle import is_tracked_callable

EXPECTED_CUSTOM_TASKS = {
    "demo.add",
    "analysis.run_stock_analysis",
    "analysis.run_market_review",
    "analysis.market_calendar_importance",
    "scheduled.analysis_daily",
    "scheduled.market_calendar",
    "scheduled.analysis_us_premarket_news",
    "scheduled.analysis_us_premarket",
    "scheduled.analysis_us_intraday",
    "scheduled.analysis_us_postmarket_review",
    "scheduled.market_data_sync_us",
    "scheduled.analysis_a_share_intraday",
    "scheduled.signal_evaluation_cn",
    "scheduled.signal_evaluation_us",
    "backtest.run",
    "quant.dataset.build",
    "quant.model.train",
    "scheduled.quant_daily_pipeline_us",
    "scheduled.quant_model_training_us",
}


def _custom_registered_tasks() -> set[str]:
    celery_app.loader.import_default_modules()
    return {
        name
        for name in celery_app.tasks
        if name.startswith(("demo.", "analysis.", "scheduled.", "backtest.", "quant."))
    }


def test_worker_registers_exactly_the_expected_custom_tasks():
    assert _custom_registered_tasks() == EXPECTED_CUSTOM_TASKS
    assert "analysis.run_batch_analysis" not in celery_app.tasks


def test_each_task_package_has_one_explicit_tasks_module_and_one_task():
    assert len(TASK_PACKAGES) == 19
    assert len(TASK_MODULES) == 19
    for package, module_name in zip(TASK_PACKAGES, TASK_MODULES):
        assert module_name == f"{package}.tasks"
        module = importlib.import_module(module_name)
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert source.count("@celery_app.task") == 1


def test_all_custom_task_names_and_job_ids_are_unique():
    scheduled = get_scheduled_task_definitions()
    celery_names = [item.celery_name for item in ON_DEMAND_TASKS]
    celery_names.extend(item.celery_task_name for item in scheduled)
    job_ids = [item.job_id for item in scheduled]

    assert len(celery_names) == len(set(celery_names)) == 19
    assert len(job_ids) == len(set(job_ids))


def test_every_schedule_definition_resolves_to_a_tracked_registered_task():
    celery_app.loader.import_default_modules()
    for definition in get_scheduled_task_definitions():
        task = celery_app.tasks.get(definition.celery_task_name)
        assert task is not None
        assert is_tracked_callable(task)


def test_all_on_demand_tasks_use_lifecycle_tracking():
    celery_app.loader.import_default_modules()
    for metadata in ON_DEMAND_TASKS:
        assert is_tracked_callable(celery_app.tasks[metadata.celery_name])


def test_removed_legacy_modules_and_batch_business_references_are_absent():
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src" / "finance_analysis"
    removed_paths = (
        source_root / "tasks" / "jobs",
        source_root / "tasks" / "scheduled_jobs.py",
        source_root / "tasks" / "celery" / "heartbeat.py",
        source_root / "tasks" / "celery" / "schedule.py",
        source_root / "tasks" / "celery" / "cron.py",
        source_root / "tasks" / "celery" / "jobs" / "analysis.py",
        source_root / "tasks" / "celery" / "jobs" / "scheduled.py",
        source_root / "tasks" / "celery" / "jobs" / "demo.py",
        source_root / "tasks" / "celery" / "jobs" / "market_calendar.py",
    )
    assert not any(path.exists() for path in removed_paths)

    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    assert "run_batch_analysis" not in source_text
    assert "submit_bot_batch_analysis" not in source_text
    assert '"batch_analysis"' not in source_text
    forbidden_imports = (
        "finance_analysis.tasks.celery.jobs.analysis",
        "finance_analysis.tasks.celery.jobs.scheduled",
        "finance_analysis.tasks.scheduled_jobs",
        "finance_analysis.tasks.celery.cron",
        "finance_analysis.tasks.celery.heartbeat",
        "finance_analysis.tasks.celery.jobs.demo import",
        "finance_analysis.tasks.celery.jobs.market_calendar import",
        "finance_analysis.tasks.jobs",
    )
    assert not any(fragment in source_text for fragment in forbidden_imports)
