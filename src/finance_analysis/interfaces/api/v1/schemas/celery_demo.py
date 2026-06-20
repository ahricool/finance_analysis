# -*- coding: utf-8 -*-
"""Schemas for demo Celery endpoints."""

from pydantic import BaseModel, Field


class CeleryAddRequest(BaseModel):
    """Request body for submitting the demo add task."""

    x: float = Field(..., description="First addend", example=1.5)
    y: float = Field(..., description="Second addend", example=2.5)


class CeleryAddResponse(BaseModel):
    """Acknowledgement after enqueueing a Celery task."""

    success: bool = Field(..., description="Whether the task was submitted", example=True)
    message: str = Field(..., description="Human-readable status message", example="Task submitted")
