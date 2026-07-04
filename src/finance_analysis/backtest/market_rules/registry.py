"""Market-specific lot, settlement and fee behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math


@dataclass(frozen=True)
class FeeBreakdown:
    commission: float = 0.0
    tax: float = 0.0
    other_fee: float = 0.0

    @property
    def total(self) -> float:
        return self.commission + self.tax + self.other_fee


class BaseMarketRules:
    market = ""
    version = "1.0.0"
    t_plus_days = 0

    def lot_size(self, trading_date: date) -> int:
        del trading_date
        raise NotImplementedError

    def normalize_buy_quantity(self, quantity: float, trading_date: date) -> int:
        lot = self.lot_size(trading_date)
        return max(0, math.floor(quantity / lot) * lot)

    def can_sell(self, *, acquired_date: date | None, trading_date: date) -> bool:
        return acquired_date is None or self.t_plus_days == 0 or acquired_date < trading_date

    def can_fill(
        self,
        *,
        side: str,
        open_price: float,
        limit_up: float | None,
        limit_down: float | None,
        suspended: bool,
    ) -> bool:
        del side, limit_up, limit_down
        return not suspended and math.isfinite(open_price) and open_price > 0

    def calculate_fees(
        self,
        *,
        side: str,
        gross_amount: float,
        commission_rate: float,
        stamp_tax_rate: float,
        transfer_fee_rate: float,
    ) -> FeeBreakdown:
        commission = max(0.0, gross_amount * commission_rate)
        return FeeBreakdown(commission=commission)


class USMarketRules(BaseMarketRules):
    market = "US"

    def lot_size(self, trading_date: date) -> int:
        del trading_date
        return 1


class CNMarketRules(BaseMarketRules):
    market = "CN"
    t_plus_days = 1

    def lot_size(self, trading_date: date) -> int:
        del trading_date
        return 100

    def can_fill(
        self,
        *,
        side: str,
        open_price: float,
        limit_up: float | None,
        limit_down: float | None,
        suspended: bool,
    ) -> bool:
        if not super().can_fill(
            side=side, open_price=open_price, limit_up=limit_up, limit_down=limit_down, suspended=suspended
        ):
            return False
        if limit_up is None or limit_down is None:
            return False
        if side == "buy" and open_price >= limit_up:
            return False
        if side == "sell" and open_price <= limit_down:
            return False
        return True

    def calculate_fees(
        self,
        *,
        side: str,
        gross_amount: float,
        commission_rate: float,
        stamp_tax_rate: float,
        transfer_fee_rate: float,
    ) -> FeeBreakdown:
        commission = max(5.0 if gross_amount else 0.0, gross_amount * commission_rate)
        tax = gross_amount * stamp_tax_rate if side == "sell" else 0.0
        return FeeBreakdown(commission=commission, tax=tax, other_fee=gross_amount * transfer_fee_rate)


class HKMarketRules(BaseMarketRules):
    market = "HK"

    def lot_size(self, trading_date: date) -> int:
        del trading_date
        raise ValueError("HK lot size is unavailable in market_data_symbol")


class MarketRuleRegistry:
    _RULES = {"US": USMarketRules(), "CN": CNMarketRules(), "HK": HKMarketRules()}

    @classmethod
    def get(cls, market: str) -> BaseMarketRules:
        try:
            return cls._RULES[market.upper()]
        except KeyError as exc:
            raise ValueError(f"Unsupported market: {market}") from exc
