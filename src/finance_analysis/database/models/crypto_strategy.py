from sqlalchemy import Column, DateTime, Index, Integer, Numeric, String, text

from finance_analysis.database.base import Base


class CryptoStrategyPeriod(Base):
    __tablename__ = "crypto_strategy_period"
    __table_args__ = (Index("uq_crypto_strategy_active", "environment", unique=True,
                            postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),)

    id = Column(Integer, primary_key=True)
    environment = Column(String(8), nullable=False)
    strategy = Column(String(32), nullable=False)
    actor_id = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    start_equity = Column(Numeric(), nullable=False)
    end_equity = Column(Numeric())
