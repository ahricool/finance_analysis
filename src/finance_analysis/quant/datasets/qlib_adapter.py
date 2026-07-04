"""Small HTTP boundary keeping Qlib objects outside the main application."""

from __future__ import annotations

import httpx

from finance_analysis.quant.config import get_quant_config
from finance_analysis.quant.exceptions import QlibUnavailableError


class QlibAdapter:
    def __init__(self, base_url: str | None = None, timeout: float = 3600):
        self.base_url = (base_url or get_quant_config().qlib_worker_url or "").rstrip("/")
        self.timeout = timeout

    def capability(self) -> dict:
        if not self.base_url: return {"status": "unavailable", "reason": "QLIB_WORKER_URL is not configured"}
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=5); response.raise_for_status(); return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "unavailable", "reason": str(exc)}

    def train(self, payload: dict) -> dict:
        if not self.base_url: raise QlibUnavailableError("QLIB_WORKER_URL is not configured")
        try:
            response = httpx.post(f"{self.base_url}/train", json=payload, timeout=self.timeout); response.raise_for_status(); return response.json()
        except httpx.HTTPError as exc:
            raise QlibUnavailableError(f"Qlib worker request failed: {exc}") from exc

    def predict(self, payload: dict) -> dict:
        if not self.base_url: raise QlibUnavailableError("QLIB_WORKER_URL is not configured")
        try:
            response = httpx.post(f"{self.base_url}/predict", json=payload, timeout=self.timeout); response.raise_for_status(); return response.json()
        except httpx.HTTPError as exc:
            raise QlibUnavailableError(f"Qlib worker prediction failed: {exc}") from exc
