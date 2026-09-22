# -*- coding: utf-8 -*-
"""Domain errors for DB portfolio cash and trade operations."""


class PortfolioError(ValueError):
    """User-facing portfolio mutation error."""


class InsufficientCashError(PortfolioError):
    def __init__(self, message: str = "现金不足，无法完成操作") -> None:
        super().__init__(message)


class InsufficientQuantityError(PortfolioError):
    def __init__(self, message: str = "卖出数量超过当前持仓") -> None:
        super().__init__(message)


class PositionClosedError(PortfolioError):
    def __init__(self, message: str = "该持仓已平仓，请重新买入开仓") -> None:
        super().__init__(message)


class UnsupportedAssetError(PortfolioError):
    def __init__(self, message: str = "当前仅支持股票/ETF，不支持期权") -> None:
        super().__init__(message)


class OperationConflictError(PortfolioError):
    def __init__(self):
        super().__init__("操作标识已用于其他记账内容，请核对后发起新操作")
