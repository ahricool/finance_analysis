"""Deterministic, point-in-time event scoring and veto rules."""

from __future__ import annotations

import math
from datetime import datetime

DEFAULT_IMPACTS = {
    "eps_surprise": 0.30, "revenue_surprise": 0.20, "guidance_up": 0.40,
    "rating_upgrade": 0.10, "guidance_down": -0.50, "offering": -0.30,
    "regulation": -0.60, "sanction": -0.60, "litigation": -0.45,
}
DEFAULT_TAU_DAYS = {"earnings": 10, "eps_surprise": 10, "revenue_surprise": 10, "guidance_up": 20, "guidance_down": 20, "regulation": 30, "sanction": 30, "litigation": 30}


def score_events(events, cutoff: datetime, impacts=None, tau_days=None) -> dict:
    impacts = impacts or DEFAULT_IMPACTS; tau_days = tau_days or DEFAULT_TAU_DAYS
    score, positive, negative, components, veto = 0.0, 0, 0, [], False
    for event in events:
        if event.available_at > cutoff: continue
        base = impacts.get(event.event_type, 0.0)
        if event.direction == "negative" and base > 0: base = -base
        if event.direction == "positive" and base < 0: base = abs(base)
        age = max(0.0, (cutoff - event.available_at).total_seconds() / 86400)
        impact = base * event.confidence * event.importance * math.exp(-age / tau_days.get(event.event_type, 7))
        score += impact
        if age <= 3:
            positive += impact > 0; negative += impact < 0
        if impact <= -0.25 and event.importance >= 0.7: veto = True
        components.append({"event_id": event.id, "event_type": event.event_type, "impact": impact})
    return {"event_score": max(-1.0, min(1.0, score)), "positive_event_count_3d": positive,
            "negative_event_count_3d": negative, "negative_event_veto": veto, "components": components}
