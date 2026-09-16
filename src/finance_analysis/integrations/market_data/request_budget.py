"""Cooperative synchronous request budgets; no abandoned background workers."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_deadline: ContextVar[float | None] = ContextVar("fundamental_deadline", default=None)
# Four HTTP phases, each with at least 0.2 seconds.
MIN_REQUEST_SECONDS = 0.8


class BudgetExhausted(TimeoutError):
    def __init__(self):
        super().__init__("skipped_budget")


def remaining_seconds() -> float | None:
    deadline = _deadline.get()
    return None if deadline is None else max(0.0, deadline - monotonic())


def check_budget() -> None:
    remaining = remaining_seconds()
    if remaining is not None and remaining < MIN_REQUEST_SECONDS:
        raise BudgetExhausted()


@contextmanager
def request_budget(seconds: float | None):
    parent = _deadline.get()
    deadline = None if seconds is None else monotonic() + max(0.0, seconds)
    if parent is not None:
        deadline = parent if deadline is None else min(parent, deadline)
    token = _deadline.set(deadline)
    try:
        yield
    finally:
        _deadline.reset(token)
