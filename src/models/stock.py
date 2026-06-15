# -*- coding: utf-8 -*-
"""Stock market ORM models."""

from typing import Any, Dict

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, Index, Integer, String, UniqueConstraint

from src.db.base import Base
from src.time_utils import utc_now


class StockDaily(Base):
    """
    股票日线数据模型

    存储每日行情数据和计算的技术指标
    支持多股票、多日期的唯一约束
    """
    __tablename__ = 'stock_daily'

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票代码（如 600519, AAPL, HK00700）
    code = Column(String(16), nullable=False, index=True)

    # 市场类型：CN / US / HK
    market = Column(String(8), nullable=False, default="CN", index=True)

    # 交易日期
    date = Column(Date, nullable=False, index=True)

    # OHLC 数据
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)

    # 成交数据
    volume = Column(Float)  # 成交量（股）
    amount = Column(Float)  # 成交额（元）
    pct_chg = Column(Float)  # 涨跌幅（%）

    # 技术指标
    ma5 = Column(Float)
    ma10 = Column(Float)
    ma20 = Column(Float)
    volume_ratio = Column(Float)  # 量比

    # 数据来源
    data_source = Column(String(50))  # 记录数据来源（如 AkshareFetcher）

    # 更新时间
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # 唯一约束：同一市场、同一股票、同一日期只能有一条数据
    __table_args__ = (
        UniqueConstraint('market', 'code', 'date', name='uix_stock_daily_market_code_date'),
        CheckConstraint("market IN ('CN', 'US', 'HK')", name='ck_stock_daily_market'),
        Index('ix_stock_daily_market_code_date', 'market', 'code', 'date'),
    )

    def __repr__(self):
        return f"<StockDaily(market={self.market}, code={self.code}, date={self.date}, close={self.close})>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'code': self.code,
            'market': self.market,
            'date': self.date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'amount': self.amount,
            'pct_chg': self.pct_chg,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'volume_ratio': self.volume_ratio,
            'data_source': self.data_source,
        }
