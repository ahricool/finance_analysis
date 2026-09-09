"""Synchronous pacing at real daily API batch boundaries, shared by nested calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import sleep


@dataclass
class _Sequence:
    started: bool = False


_sequence: ContextVar[_Sequence | None] = ContextVar("daily_batch_sequence", default=None)


@contextmanager
def daily_batch_scope():
    if _sequence.get() is not None:
        yield
        return
    token = _sequence.set(_Sequence())
    try:
        yield
    finally:
        _sequence.reset(token)


def before_daily_batch() -> None:
    sequence = _sequence.get()
    if sequence is None:
        raise RuntimeError("Daily API batches require daily_batch_scope")
    if sequence.started:
        sleep(10)
    sequence.started = True


def reset_daily_batch_sequence() -> None:
    """The delayed retry already waited five minutes; its first batch needs no extra wait."""
    sequence = _sequence.get()
    if sequence is not None:
        sequence.started = False
