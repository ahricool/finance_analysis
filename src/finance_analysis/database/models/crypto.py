"""PostgreSQL facts for Binance BTCUSDT and the V0.1 strategy."""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from finance_analysis.core.time import utc_now
from finance_analysis.database.base import Base


class CryptoStrategyState(Base):
    __tablename__ = "crypto_strategy_state"
    __table_args__ = (
        CheckConstraint("position_state IN ('FLAT', 'LONG')", name="ck_crypto_state_position"),
        CheckConstraint("position_pct >= 0 AND position_pct <= 1", name="ck_crypto_state_pct"),
    )
    symbol = Column(String(16), primary_key=True)
    position_state = Column(String(8), nullable=False, default="FLAT")
    position_pct = Column(Numeric(18, 12), nullable=False, default=0, server_default="0")
    average_entry_price = Column(Numeric(30, 12))
    entry_price = Column(Numeric(30, 12))
    entry_time = Column(DateTime(timezone=True))
    highest_price_since_entry = Column(Numeric(30, 12))
    initial_stop = Column(Numeric(30, 12))
    trailing_stop = Column(Numeric(30, 12))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CryptoStrategySnapshot(Base):
    __tablename__ = "crypto_strategy_snapshot"
    __table_args__ = (
        UniqueConstraint("symbol", "evaluated_at", name="uq_crypto_snapshot_symbol_evaluated"),
        CheckConstraint("position_before >= 0 AND position_before <= 1", name="ck_crypto_snapshot_before"),
        CheckConstraint("position_after >= 0 AND position_after <= 1", name="ck_crypto_snapshot_after"),
        CheckConstraint("position_delta = position_after - position_before", name="ck_crypto_snapshot_delta"),
    )
    id = Column(Integer, primary_key=True)
    symbol = Column(String(16), nullable=False)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    regime = Column(String(16), nullable=False)
    setup = Column(String(16), nullable=False)
    action = Column(String(8), nullable=False)
    price = Column(Numeric(30, 12), nullable=False)
    ema20_1h = Column(Numeric(30, 12))
    ema50_1h = Column(Numeric(30, 12))
    ema20_15m = Column(Numeric(30, 12))
    breakout_level_15m = Column(Numeric(30, 12))
    volume_ratio_15m = Column(Numeric(30, 12))
    atr14_15m = Column(Numeric(30, 12))
    initial_stop = Column(Numeric(30, 12))
    trailing_stop = Column(Numeric(30, 12))
    position_state = Column(String(8), nullable=False)
    position_before = Column(Numeric(18, 12))
    position_after = Column(Numeric(18, 12))
    position_delta = Column(Numeric(18, 12))
    average_entry_price = Column(Numeric(30, 12))
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
