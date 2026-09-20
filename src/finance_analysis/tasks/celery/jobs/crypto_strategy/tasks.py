"""Evaluate BTC after each quarter-hour close."""

import asyncio

import httpx

from finance_analysis.crypto.config import get_crypto_config
from finance_analysis.crypto.service import CryptoService
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition
from finance_analysis.tasks.lifecycle import TaskSkipped, track_task

DEFINITION = require_scheduled_task_definition("crypto_btc_strategy")


@celery_app.task(
    name=DEFINITION.celery_task_name,
    autoretry_for=(httpx.HTTPError, ValueError),
    retry_kwargs={"max_retries": 2},
    default_retry_delay=30,
)
@track_task(
    task_type=DEFINITION.task_type,
    task_name=DEFINITION.name,
    source="celery",
    trigger_source="scheduler",
    scheduler_job_id=DEFINITION.job_id,
    record_result=True,
    strip_lifecycle_kwargs=True,
)
def run_crypto_btc_strategy(**kwargs):
    if not get_crypto_config().enabled:
        raise TaskSkipped("BTC 策略已停用")
    return asyncio.run(CryptoService().run())
