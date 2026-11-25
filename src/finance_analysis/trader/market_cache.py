"""Versioned, read-only Trader cache of confirmed Stock Streamer candles."""
from collections.abc import Iterable
import time


class ConfirmedBarCache:
    """A Redis version check each round; one batched fetch for changed symbols.

    Periodic full reconciliation also handles legacy (unversioned) cache keys,
    Redis restarts, and expiration. Never reuse stale data after a failed read.
    """

    def __init__(self, repository, reconcile_seconds=60):
        self.repository = repository
        self.reconcile_seconds = reconcile_seconds
        self.snapshots = {}
        self.revisions = {}
        self.last_full = None

    async def refresh(self, symbols: Iterable[str]):
        symbols = set(symbols)
        for symbol in self.snapshots.keys() - symbols:
            self.snapshots.pop(symbol)
            self.revisions.pop(symbol, None)
        now = time.monotonic()
        full = self.last_full is None or now - self.last_full >= self.reconcile_seconds
        try:
            revisions = await self.repository.get_bar_revisions(sorted(symbols))
            changed = [
                symbol for symbol in sorted(symbols)
                if full or symbol not in self.snapshots or self.revisions.get(symbol) != revisions.get(symbol)
            ]
            fresh = await self.repository.get_confirmed_bar_snapshots(changed)
            for symbol in changed:
                revision, bars = fresh[symbol]
                self.revisions[symbol] = revision
                self.snapshots[symbol] = tuple(bars)
        except Exception:
            self.snapshots.clear()
            self.revisions.clear()
            self.last_full = None
            raise
        if full:
            self.last_full = now
        # Freeze this round's mapping, without copying unchanged candle arrays.
        return dict(self.snapshots)
