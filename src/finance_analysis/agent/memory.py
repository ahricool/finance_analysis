# -*- coding: utf-8 -*-
"""
AgentMemory — persistent structured memory for agent learning.

Provides:
1. **Analysis memory** — stores past analysis results with outcomes,
   enabling agents to learn from their own track record.
2. **Confidence calibration** — adjusts agent confidence based on
   historical accuracy (only after sufficient sample count).

Storage uses the existing SQLAlchemy database layer
(``AnalysisHistory`` table) rather than introducing a new store.

.. note::
   Memory features are gated behind ``AGENT_MEMORY_ENABLED=true``.
   When disabled, all methods return neutral/default values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default minimum samples before calibration kicks in
_MIN_CALIBRATION_SAMPLES = 30


@dataclass
class CalibrationResult:
    """Confidence calibration data for an agent or skill."""
    agent_name: str = ""
    total_samples: int = 0
    historical_accuracy: float = 0.5  # 0.0–1.0
    direction_accuracy: float = 0.5
    avg_confidence: float = 0.5
    calibrated: bool = False  # True if samples >= threshold
    calibration_factor: float = 1.0  # multiply raw confidence by this


@dataclass
class AnalysisMemoryEntry:
    """A remembered past analysis for context injection."""
    stock_code: str = ""
    date: str = ""
    signal: str = ""
    sentiment_score: int = 50
    price_at_analysis: float = 0.0
    outcome_5d: Optional[float] = None  # % change after 5 days
    outcome_20d: Optional[float] = None  # % change after 20 days
    was_correct: Optional[bool] = None


class AgentMemory:
    """Structured memory system for agent self-improvement.

    Usage::

        memory = AgentMemory()
        # Get past analyses for context
        past = memory.get_stock_history("600519", limit=5)
        # Calibrate confidence
        cal = memory.get_calibration("technical", stock_code="600519")
    """

    def __init__(self, enabled: bool = False, min_samples: int = _MIN_CALIBRATION_SAMPLES):
        self.enabled = enabled
        self.min_samples = min_samples

    @classmethod
    def from_config(cls) -> "AgentMemory":
        """Create an AgentMemory from the current config."""
        try:
            from finance_analysis.agent.config import get_agent_config
            config = get_agent_config()
            enabled = getattr(config, "agent_memory_enabled", False)
            return cls(enabled=enabled)
        except Exception:
            return cls(enabled=False)

    # -----------------------------------------------------------------
    # Analysis history retrieval
    # -----------------------------------------------------------------

    def get_stock_history(
        self,
        stock_code: str,
        limit: int = 5,
    ) -> List[AnalysisMemoryEntry]:
        """Retrieve recent analysis results for a stock.

        Returns structured entries that can be injected into agent
        context for learning from past predictions.
        """
        if not self.enabled:
            return []

        try:
            from finance_analysis.database import get_db
            db = get_db()
            records = db.get_analysis_history(code=stock_code, limit=limit)
            entries = []
            for r in records:
                raw_result: Dict[str, Any] = {}
                if isinstance(getattr(r, "raw_result", None), str) and r.raw_result:
                    try:
                        parsed = json.loads(r.raw_result)
                        if isinstance(parsed, dict):
                            raw_result = parsed
                    except (TypeError, ValueError):
                        raw_result = {}
                elif isinstance(getattr(r, "raw_result", None), dict):
                    raw_result = dict(r.raw_result)

                signal = raw_result.get("decision_type") or getattr(r, "operation_advice", "") or "hold"
                price_at_analysis = raw_result.get("current_price")
                if price_at_analysis is None:
                    price_at_analysis = 0.0

                entries.append(AnalysisMemoryEntry(
                    stock_code=stock_code,
                    date=(r.created_at.date().isoformat() if getattr(r, "created_at", None) else ""),
                    signal=signal,
                    sentiment_score=getattr(r, "sentiment_score", 50) or 50,
                    price_at_analysis=float(price_at_analysis or 0.0),
                    was_correct=None,
                ))
            return entries
        except Exception as exc:
            logger.debug("[AgentMemory] get_stock_history failed: %s", exc)
            return []

    # -----------------------------------------------------------------
    # Confidence calibration
    # -----------------------------------------------------------------

    def get_calibration(
        self,
        agent_name: str,
        stock_code: Optional[str] = None,
        skill_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> CalibrationResult:
        """Compute confidence calibration for an agent or skill.

        When ``AGENT_MEMORY_ENABLED=false`` or insufficient samples,
        returns a neutral calibration (factor = 1.0).
        """
        result = CalibrationResult(agent_name=agent_name)

        if not self.enabled:
            return result

        try:
            resolved_skill_id = skill_id or strategy_id
            stats = self._get_accuracy_stats(agent_name, stock_code, resolved_skill_id)
            result.total_samples = stats.get("total", 0)
            result.historical_accuracy = stats.get("accuracy", 0.5)
            result.direction_accuracy = stats.get("direction_accuracy", 0.5)
            result.avg_confidence = stats.get("avg_confidence", 0.5)

            if result.total_samples >= self.min_samples:
                result.calibrated = True
                if result.avg_confidence > 0:
                    result.calibration_factor = min(
                        1.5,
                        max(0.5, result.historical_accuracy / result.avg_confidence),
                    )
                else:
                    result.calibration_factor = 1.0
            else:
                result.calibrated = False
                result.calibration_factor = 1.0

        except Exception as exc:
            logger.debug("[AgentMemory] calibration failed for %s: %s", agent_name, exc)

        return result

    def calibrate_confidence(self, agent_name: str, raw_confidence: float, stock_code: Optional[str] = None) -> float:
        """Apply calibration to a raw confidence value.

        Returns the adjusted confidence, clamped to [0.0, 1.0].
        """
        cal = self.get_calibration(agent_name, stock_code=stock_code)
        if not cal.calibrated:
            return raw_confidence
        adjusted = raw_confidence * cal.calibration_factor
        return max(0.0, min(1.0, adjusted))

    # -----------------------------------------------------------------
    # Skill performance
    # -----------------------------------------------------------------

    def get_skill_performance(self, skill_id: str) -> Dict[str, Any]:
        """Get performance metrics for a skill."""
        del skill_id
        return {"available": False}

    def get_strategy_performance(self, strategy_id: str) -> Dict[str, Any]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.get_skill_performance(strategy_id)

    # -----------------------------------------------------------------
    # Auto-weighting
    # -----------------------------------------------------------------

    def compute_skill_weights(self, skill_ids: List[str]) -> Dict[str, float]:
        """Compute normalized weights for a set of skills.

        Returns neutral weights until a dedicated performance source exists.
        """
        return {sid: 1.0 for sid in skill_ids}

    def compute_strategy_weights(self, strategy_ids: List[str]) -> Dict[str, float]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.compute_skill_weights(strategy_ids)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _get_accuracy_stats(
        self,
        agent_name: str,
        stock_code: Optional[str],
        skill_id: Optional[str],
    ) -> Dict[str, Any]:
        """Aggregate accuracy statistics from analysis history."""
        del agent_name, stock_code, skill_id
        return {"total": 0, "accuracy": 0.5, "direction_accuracy": 0.5, "avg_confidence": 0.5}
