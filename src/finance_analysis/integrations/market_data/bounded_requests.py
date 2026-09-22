"""Small bounded fan-out for independent requests, retaining completed results at deadline."""

from concurrent.futures import FIRST_COMPLETED, wait
from contextvars import copy_context

from finance_analysis.core.retry import retry_call
from .request_budget import BudgetExhausted, remaining_seconds


def _check_deadline():
    remaining = remaining_seconds()
    if remaining is not None and remaining <= 0:
        raise BudgetExhausted()


def bounded_results(calls, executor, max_pending):
    """Yield (key, value, error) in completion order; workers never mutate batch results.

    Executors are shared and fixed-size: timed-out SDK calls may finish in the background,
    but subsequent evaluations cannot create an unbounded number of replacement threads.
    """
    queued = iter(calls.items())
    pending = {}

    def invoke(call):
        _check_deadline()
        return call()

    def fill():
        while len(pending) < max_pending:
            remaining = remaining_seconds()
            if remaining is not None and remaining <= 0:
                return
            try:
                key, call = next(queued)
            except StopIteration:
                return
            pending[executor.submit(copy_context().run, invoke, call)] = key

    try:
        fill()
        while pending:
            done, _ = wait(pending, timeout=remaining_seconds(), return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                key = pending.pop(future)
                try:
                    value = future.result()
                except Exception as exc:
                    yield key, None, exc
                else:
                    yield key, value, None
            fill()
        for future, key in pending.items():
            # Harvest races at the deadline before declaring unfinished work unavailable.
            if future.done() and not future.cancelled():
                try:
                    value = future.result()
                except Exception as exc:
                    yield key, None, exc
                else:
                    yield key, value, None
            else:
                future.cancel()
                yield key, None, BudgetExhausted()
        for key, _ in queued:
            yield key, None, BudgetExhausted()
    finally:
        for future in pending:
            future.cancel()


def budgeted_retry(operation):
    """Preserve existing retries, but do not start a retry beyond the inherited deadline."""

    def attempt():
        _check_deadline()
        return operation()

    def before_wait(delay):
        remaining = remaining_seconds()
        if remaining is not None and remaining <= delay:
            raise BudgetExhausted()

    return retry_call(attempt, before_wait=before_wait)
