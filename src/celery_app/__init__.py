# -*- coding: utf-8 -*-
"""Celery application package for async heavy workloads (e.g. backtests)."""

from src.celery_app.app import celery_app

__all__ = ["celery_app"]
