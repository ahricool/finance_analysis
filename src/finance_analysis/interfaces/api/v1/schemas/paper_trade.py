from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class StrategyConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    strategy_type: Literal["ema_cross", "perpetual_drive"] = "ema_cross"
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,32}$")
    fast: int | None = Field(default=None, ge=2, le=40)
    slow: int | None = Field(default=None, ge=3, le=90)
    drive_range_pct: Decimal = Field(default=Decimal("0.8"), gt=0, le=10)
    drive_move_pct: Decimal = Field(default=Decimal("1.2"), gt=0, le=20)
    drive_efficiency: Decimal = Field(default=Decimal("0.48"), gt=0, le=1)
    drive_relative_pct: Decimal = Field(default=Decimal("0.8"), ge=0, le=10)
    direction: Literal["LONG", "BOTH"]
    notional: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    margin: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    max_position: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    leverage_limit: int = Field(ge=1, le=125)
    max_loss: Decimal = Field(gt=0, max_digits=20, decimal_places=8)
    stop_pct: Decimal = Field(gt=0, lt=100, decimal_places=4)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.strategy_type == "ema_cross" and (self.fast is None or self.slow is None or self.fast >= self.slow):
            raise ValueError("Fast EMA must be shorter than slow EMA")
        if self.notional > self.max_position:
            raise ValueError("Notional cannot exceed maximum position")
        if self.notional * self.stop_pct / 100 > self.max_loss:
            raise ValueError("Planned stop loss exceeds loss limit")
        return self


class StrategyControl(BaseModel):
    enabled: bool


class ManualOrder(BaseModel):
    request_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,32}$")
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"]
    quantity: Decimal = Field(gt=0, max_digits=28, decimal_places=12)
    price: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=12)
    trigger_price: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=12)
    reduce_only: bool = False
    confirm_demo: Literal[True]

    @model_validator(mode="after")
    def validate_price(self):
        if (self.order_type == "LIMIT") != (self.price is not None):
            raise ValueError("Limit order requires price")
        if (self.order_type in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}) != (self.trigger_price is not None):
            raise ValueError("Conditional order requires trigger price")
        return self


class OrderAction(BaseModel):
    request_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,32}$")
    exchange_id: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    algo: bool = False
    position_side: Literal["BOTH", "LONG", "SHORT"] = "BOTH"
    confirm_demo: Literal[True]


class ClosePosition(BaseModel):
    request_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,32}$")
    position_side: Literal["BOTH", "LONG", "SHORT"] = "BOTH"
    confirm_demo: Literal[True]
    expected_quantity: Decimal = Field(max_digits=28, decimal_places=12)
    expected_entry_price: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=12)


class PaperConnection(BaseModel):
    status: str
    stream_connected: bool
    reason: str | None = None


class PaperTradeControl(BaseModel):
    enabled: bool
    updated_at: str | None


class PaperSnapshot(BaseModel):
    trade_control: PaperTradeControl
    connection: PaperConnection
    view: dict | None
    equity: list[dict]
    strategies: list[dict]
    intents: list[dict]
    orders: list[dict]
    algos: list[dict]
    trades: list[dict]
    income: list[dict]
    realized_net: str | None
