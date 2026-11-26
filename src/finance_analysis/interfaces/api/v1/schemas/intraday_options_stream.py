"""Versioned, connection-local delta transport for the intraday options snapshot.

Paths are JSON array indices or object keys. Values (including null) are literal
replacements; missing keys are removed explicitly. The original REST snapshot
and legacy stream clients remain unchanged.
"""
from typing import Any, Literal, NotRequired, TypedDict


class SnapshotOperation(TypedDict):
    op: Literal['set', 'remove', 'insert']
    path: list[str | int]
    value: NotRequired[Any]


class SnapshotDelta(TypedDict):
    base_revision: int
    revision: int
    operations: list[SnapshotOperation]


# These collections have durable identities. Preserve existing records when an
# event is prepended, a position exits or the observation pool changes.
_IDENTITIES = {
    ('items',): 'symbol',
    ('minutes',): 'timestamp',
    ('simulation', 'states'): 'symbol',
    ('simulation', 'trades'): 'id',
    ('simulation', 'events'): 'id',
    ('simulation', 'statistics'): 'label',
}


def _diff(old, new, path, operations):
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old:
            if key in new:
                continue
            operations.append({'op': 'remove', 'path': [*path, key]})
        for key, value in new.items():
            if key in old:
                _diff(old[key], value, [*path, key], operations)
            else:
                operations.append({'op': 'set', 'path': [*path, key], 'value': value})
        return
    if isinstance(old, list) and isinstance(new, list):
        identity = _IDENTITIES.get(tuple(path))
        if identity and _diff_collection(old, new, path, identity, operations):
            return
        if not identity and len(old) == len(new):
            for index, (previous, current) in enumerate(zip(old, new)):
                _diff(previous, current, [*path, index], operations)
            return
    operations.append({'op': 'set', 'path': path, 'value': new})


def _diff_collection(old, new, path, identity, operations):
    if any(not isinstance(row, dict) or identity not in row for row in [*old, *new]):
        return False
    old_ids = [row[identity] for row in old]
    new_ids = [row[identity] for row in new]
    old_set, new_set = set(old_ids), set(new_ids)
    if len(old_set) != len(old_ids) or len(new_set) != len(new_ids):
        return False
    if [key for key in old_ids if key in new_set] != [key for key in new_ids if key in old_set]:
        # Rare changes in relative ordering: replace the collection atomically.
        return False
    by_id = dict(zip(old_ids, old))
    for index in range(len(old_ids) - 1, -1, -1):
        if old_ids[index] not in new_set:
            operations.append({'op': 'remove', 'path': [*path, index]})
    for index, (key, row) in enumerate(zip(new_ids, new)):
        if key not in old_set:
            operations.append({'op': 'insert', 'path': [*path, index], 'value': row})
        else:
            _diff(by_id[key], row, [*path, index], operations)
    return True


def _stable_snapshot(snapshot: dict) -> dict:
    # The DB queries for states/trades have no business ordering. PostgreSQL can
    # return a different order after row updates even when payloads are unchanged.
    simulation = snapshot.get('simulation')
    if not isinstance(simulation, dict):
        return snapshot
    ordered = dict(simulation)
    for field, identity in (('states', 'symbol'), ('trades', 'id')):
        rows = simulation.get(field)
        if isinstance(rows, list) and all(isinstance(row, dict) and identity in row for row in rows):
            ordered[field] = sorted(rows, key=lambda row: row[identity])
    return {**snapshot, 'simulation': ordered}


class IntradayOptionsStream:
    """One baseline per ordered WS/SSE connection; reconnects always reset it."""

    def __init__(self):
        self.previous: dict | None = None
        self.revision = 0

    def encode(self, frame: dict) -> dict:
        current = _stable_snapshot(frame['intraday_options'])
        previous = self.previous
        revision = self.revision + 1
        if previous is None or any(previous[k] != current[k] for k in ('trading_date', 'version')):
            self.previous, self.revision = current, revision
            return {**frame, 'intraday_options': current, 'intraday_options_revision': revision}
        operations: list[SnapshotOperation] = []
        _diff({k: v for k, v in previous.items() if k != 'generated_at'},
              {k: v for k, v in current.items() if k != 'generated_at'}, [], operations)
        delta: SnapshotDelta = {
            'base_revision': self.revision,
            'revision': revision,
            'operations': operations,
        }
        self.previous, self.revision = current, revision
        # Empty operations are a successful, lightweight snapshot heartbeat.
        return {'type': 'quotes', 'quotes': [], 'generated_at': frame['generated_at'],
                'intraday_options_delta': delta}


class SnapshotStream:
    """Encode a baseline and ordered field changes for one subscription."""

    def __init__(self):
        self.previous = None
        self.revision = 0

    def encode(self, current):
        self.revision += 1
        if self.previous is None:
            frame = {**current, "revision": self.revision}
        else:
            operations = []
            _diff(self.previous, current, [], operations)
            frame = {"revision": self.revision, "operations": operations}
        self.previous = current
        return frame
