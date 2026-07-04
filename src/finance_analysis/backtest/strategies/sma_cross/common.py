"""Shared signal semantics; execution remains engine-native."""

from __future__ import annotations

from collections import deque


class SmaCrossSignalState:
    def __init__(self, fast_window: int, slow_window: int):
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.closes: deque[float] = deque(maxlen=slow_window)
        self.previous_fast: float | None = None
        self.previous_slow: float | None = None

    def update(self, close: float) -> str | None:
        self.closes.append(float(close))
        if len(self.closes) < self.slow_window:
            return None
        values = list(self.closes)
        fast = sum(values[-self.fast_window:]) / self.fast_window
        slow = sum(values) / self.slow_window
        signal = None
        if self.previous_fast is not None and self.previous_slow is not None:
            if self.previous_fast <= self.previous_slow and fast > slow:
                signal = "buy"
            elif self.previous_fast >= self.previous_slow and fast < slow:
                signal = "sell"
        self.previous_fast, self.previous_slow = fast, slow
        return signal
