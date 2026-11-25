from pydantic import BaseModel, StrictBool


class LiveControlUpdate(BaseModel):
    enabled: StrictBool


class LiveControl(BaseModel):
    enabled: bool
    updated_at: str | None


class LiveSnapshot(BaseModel):
    environment: str
    control: LiveControl
    connection: dict
    view: dict | None
    equity: list[dict]
    orders: list[dict]
    algos: list[dict]
    trades: list[dict]
    income: list[dict]
    realized_net: str | None
    control_events: list[dict]
    strategy_count: int
