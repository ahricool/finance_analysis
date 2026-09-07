"""ATR stops only tighten, never widen."""

from decimal import Decimal


def initial_stop(price: Decimal, atr14: Decimal) -> Decimal:
    return max(Decimal(0), price - 2 * atr14)


def trailing_stop(highest: Decimal, atr14: Decimal, previous: Decimal | None) -> Decimal:
    return max(previous or Decimal(0), highest - Decimal("2.5") * atr14)
