# -*- coding: utf-8 -*-
"""Demo endpoints that enqueue Celery tasks."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from finance_analysis.interfaces.api.v1.schemas.celery_demo import CeleryAddRequest, CeleryAddResponse
from finance_analysis.tasks.celery.jobs.demo import add

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/add",
    response_model=CeleryAddResponse,
    summary="提交 demo 加法 Celery 任务",
    description="接收 x、y 两个参数并异步执行加法任务，立即返回提交成功。",
)
def submit_add_task(request: CeleryAddRequest) -> CeleryAddResponse:
    add.delay(request.x, request.y)
    logger.info("Submitted demo add task: x=%s y=%s", request.x, request.y)
    return CeleryAddResponse(success=True, message="Task submitted")
