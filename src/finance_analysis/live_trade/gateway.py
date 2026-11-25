"""Internal future-strategy contract. No production execution adapter in v1."""

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from finance_analysis.database.repositories import live_trade as repo


class Action(StrEnum):
    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    CANCEL_ORDER = "CANCEL_ORDER"
    MODIFY_ORDER = "MODIFY_ORDER"
    PLACE_CONDITIONAL = "PLACE_CONDITIONAL"
    CANCEL_CONDITIONAL = "CANCEL_CONDITIONAL"
    SET_LEVERAGE = "SET_LEVERAGE"
    SET_MARGIN_MODE = "SET_MARGIN_MODE"
    SET_POSITION_MODE = "SET_POSITION_MODE"


@dataclass(frozen=True)
class LiveIntent:
    strategy_id: str
    symbol: str
    action: Action
    request_id: str
    parameters: dict = field(default_factory=dict)


# Future explicitly implemented strategies may register here; v1 has none.
STRATEGIES = MappingProxyType({})


class ExecutionDenied(Exception):
    pass


class LiveGateway:
    """Central fail-closed contract, deliberately not connected to any order client."""

    def __init__(self, state_reader=repo.control, registry=STRATEGIES):
        self._state_reader = state_reader
        self._registry = registry

    def submit(self, intent: LiveIntent):
        try:
            state = self._state_reader()
            enabled = state["enabled"] is True
        except Exception:
            raise ExecutionDenied("LIVE_CONTROL_UNAVAILABLE") from None
        if not enabled:
            raise ExecutionDenied("LIVE_TRADING_DISABLED")
        if intent.strategy_id not in self._registry:
            raise ExecutionDenied("LIVE_STRATEGY_NOT_REGISTERED")
        # Even with a local mock registration, v1 has no execution transport.
        raise ExecutionDenied("LIVE_EXECUTION_NOT_IMPLEMENTED")
