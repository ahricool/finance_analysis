"""A-share signal evaluation Celery task package."""

from .tasks import evaluate_signals_cn

__all__ = ["evaluate_signals_cn"]
