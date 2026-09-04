# -*- coding: utf-8 -*-
"""
===================================
AkShareProvider - AkShare 市场数据能力
===================================

数据来源：
1. 东方财富爬虫（通过 akshare 库） - 默认数据源
2. 新浪财经接口 - 备选数据源
3. 腾讯财经接口 - 备选数据源

特点：免费、无需 Token、数据全面
风险：爬虫机制易被反爬封禁

防封禁策略：
1. 每次请求前随机休眠 2-5 秒
2. 随机轮换 User-Agent
3. 使用 tenacity 实现指数退避重试
4. 熔断器机制：连续失败后自动冷却

增强数据：
- 实时行情：量比、换手率、市盈率、市净率、总市值、流通市值
- 筹码分布：获利比例、平均成本、筹码集中度
"""

import logging
import os
import random
import re
import time
from datetime import date, datetime
from types import SimpleNamespace
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from finance_analysis.patches.eastmoney_patch import eastmoney_patch
from finance_analysis.integrations.market_data.config import get_data_provider_config
from finance_analysis.integrations.market_data.errors import DataFetchError, RateLimitError
from finance_analysis.integrations.market_data.codes import (
    is_etf_code,
    is_hk_code,
    is_us_code,
    to_sina_tx_symbol,
    is_bse_code,
    is_hk_stock_code,
    is_kc_cy_stock,
    is_st_stock,
    normalize_stock_code,
)
from finance_analysis.integrations.market_data.models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
    Market,
    MarketIndex,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
)
from finance_analysis.integrations.market_data.normalizer import (
    STANDARD_COLUMNS,
    bars_from_frame,
    canonical_symbol,
    currency_for_market,
    infer_market,
    quote_from_value,
)
from finance_analysis.integrations.market_data.realtime_types import (
    UnifiedRealtimeQuote,
    ChipDistribution,
    RealtimeSource,
    get_realtime_circuit_breaker,
    get_chip_circuit_breaker,
    safe_float,
    safe_int,  # 使用统一的类型转换函数
)
from finance_analysis.integrations.market_data.providers.us_index_mapping import is_us_index_code

logger = logging.getLogger(__name__)

SINA_REALTIME_ENDPOINT = "hq.sinajs.cn/list"
TENCENT_REALTIME_ENDPOINT = "qt.gtimg.cn/q"


# User-Agent 池，用于随机轮换
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# 缓存实时行情数据（避免重复请求）
# TTL 设为 20 分钟 (1200秒)：
# - 批量分析场景：通常 30 只股票在 5 分钟内分析完，20 分钟足够覆盖
# - 实时性要求：股票分析不需要秒级实时数据，20 分钟延迟可接受
# - 防封禁：减少 API 调用频率
_realtime_cache: Dict[str, Any] = {"data": None, "timestamp": 0, "ttl": 1200}  # 20分钟缓存有效期

# ETF 实时行情缓存
_etf_realtime_cache: Dict[str, Any] = {"data": None, "timestamp": 0, "ttl": 1200}  # 20分钟缓存有效期


def _classify_realtime_http_error(exc: Exception) -> Tuple[str, str]:
    """
    Classify Sina/Tencent realtime quote failures into stable categories.
    """
    detail = str(exc).strip() or type(exc).__name__
    lowered = detail.lower()

    remote_disconnect_keywords = (
        "remotedisconnected",
        "remote end closed connection without response",
        "connection aborted",
        "connection broken",
        "protocolerror",
        "chunkedencodingerror",
    )
    timeout_keywords = (
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
    )
    rate_limit_keywords = (
        "banned",
        "blocked",
        "频率",
        "rate limit",
        "too many requests",
        "429",
        "限制",
        "forbidden",
        "403",
    )

    if any(keyword in lowered for keyword in remote_disconnect_keywords):
        return "remote_disconnect", detail
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)) or any(
        keyword in lowered for keyword in timeout_keywords
    ):
        return "timeout", detail
    if any(keyword in lowered for keyword in rate_limit_keywords):
        return "rate_limit_or_anti_bot", detail
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error", detail
    return "unknown_request_error", detail


def _build_realtime_failure_message(
    source_name: str,
    endpoint: str,
    stock_code: str,
    symbol: str,
    category: str,
    detail: str,
    elapsed: float,
    error_type: str,
) -> str:
    return (
        f"{source_name} 实时行情接口失败: endpoint={endpoint}, stock_code={stock_code}, "
        f"symbol={symbol}, category={category}, error_type={error_type}, "
        f"elapsed={elapsed:.2f}s, detail={detail}"
    )


class AkShareProvider:
    """
    Akshare 数据源实现

    优先级：1（最高）
    数据来源：东方财富网爬虫

    关键策略：
    - 每次请求前随机休眠 2.0-5.0 秒
    - 随机 User-Agent 轮换
    - 失败后指数退避重试（最多3次）
    """

    name = "akshare"

    def __init__(self, sleep_min: float = 2.0, sleep_max: float = 5.0):
        """
        初始化 AkShareProvider

        Args:
            sleep_min: 最小休眠时间（秒）
            sleep_max: 最大休眠时间（秒）
        """
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: Optional[float] = None
        # 东财补丁开启才执行打补丁操作
        if get_data_provider_config().enable_eastmoney_patch:
            eastmoney_patch()

    @staticmethod
    def random_sleep(min_seconds: float, max_seconds: float) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))

    @staticmethod
    def _canonical_base(code: str) -> str:
        canonical = str(code or "").strip().upper()
        if canonical.endswith((".SH", ".SZ", ".HK")):
            return canonical[:-3]
        raise ValueError(f"AKShare daily history requires a canonical CN/HK symbol: {code}")

    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult:
        if request.adjustment is not Adjustment.FORWARD:
            raise ValueError("AKShare daily storage reads require adjustment='forward'")
        result = BatchBarResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            market = infer_market(symbol)
            try:
                frame = self._fetch_daily_frame(
                    SimpleNamespace(code=symbol, market=market.value),
                    request.start_date,
                    request.end_date,
                )
                bars = bars_from_frame(
                    frame,
                    symbol=symbol,
                    provider=self.name,
                    interval="1d",
                    adjustment=Adjustment.FORWARD,
                )
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult:
        import akshare as ak

        result = BatchBarResult()
        period = request.interval.removesuffix("m")
        for value in request.symbols:
            symbol = canonical_symbol(value)
            if infer_market(symbol) is not Market.CN:
                result.failed_symbols[symbol] = "AKShare minute bars currently support CN only"
                continue
            try:
                raw = ak.stock_zh_a_hist_min_em(
                    symbol=normalize_stock_code(symbol),
                    start_date=request.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=request.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                    period=period,
                    adjust="",
                )
                bars = bars_from_frame(
                    raw.rename(columns={"时间": "bar_time", "成交量": "volume", "成交额": "amount"}),
                    symbol=symbol,
                    provider=self.name,
                    interval=request.interval,
                    volume_multiplier=100,
                )
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        result = BatchQuoteResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                raw = self.get_realtime_quote(symbol)
                payload = raw.to_dict() if raw is not None else None
                if payload is not None and infer_market(symbol) is Market.CN and payload.get("volume") is not None:
                    payload["volume"] = int(payload["volume"] * 100)
                quote = quote_from_value(payload, symbol=symbol, provider=self.name)
                if quote is None:
                    result.missing_symbols.append(symbol)
                else:
                    result.data[symbol] = quote
                    result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        import akshare as ak

        result = BatchInstrumentResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            market = infer_market(symbol)
            try:
                if market is Market.CN:
                    frame = ak.stock_individual_info_em(symbol=normalize_stock_code(symbol))
                    names = frame.loc[frame["item"] == "股票简称", "value"] if not frame.empty else []
                    name = str(names.iloc[0]).strip() if len(names) else ""
                else:
                    raw_quote = self.get_realtime_quote(symbol)
                    name = str(raw_quote.name).strip() if raw_quote is not None else ""
                if not name:
                    result.missing_symbols.append(symbol)
                    continue
                result.data[symbol] = InstrumentInfo(
                    symbol=symbol,
                    market=market,
                    name=name,
                    provider=self.name,
                    currency=currency_for_market(market),
                    exchange=symbol.rsplit(".", 1)[1],
                    instrument_type="stock",
                )
                result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_instruments(self, market: str) -> list[dict[str, Any]]:
        """Fallback A-share directory. Failures are propagated and never imply delisting."""
        normalized = str(getattr(market, "value", market)).upper()
        if normalized != "CN":
            raise ValueError("AkShare instrument directory currently supports CN only")
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        records = []
        for row in frame.to_dict("records"):
            native = str(row.get("code") or row.get("证券代码") or "").zfill(6)
            code = canonical_symbol(native, "CN")
            records.append(
                {
                    "market": "CN",
                    "code": code,
                    "native_code": native,
                    "name": str(row.get("name") or row.get("证券简称") or code),
                    "instrument_type": "STOCK",
                    "currency": "CNY",
                    "listing_date": None,
                    "listing_status": "ACTIVE",
                    "source": "AKSHARE",
                    "metadata": {},
                }
            )
        return records

    def fetch_index_members(self, index_code: str) -> list[dict[str, Any]]:
        """Fetch current CSI constituents without membership history."""
        import akshare as ak

        frame = ak.index_stock_cons_csindex(symbol=str(index_code))
        records = []
        for row in frame.to_dict("records"):
            native = str(row.get("成分券代码") or row.get("品种代码") or row.get("code") or "").zfill(6)
            code = canonical_symbol(native, "CN")
            name = str(row.get("成分券名称") or row.get("品种名称") or row.get("name") or code).strip()
            records.append(
                {
                    "market": "CN",
                    "code": code,
                    "native_code": native,
                    "name": name,
                    "instrument_type": "STOCK",
                    "currency": "CNY",
                    "listing_status": "ACTIVE",
                    "source": "AKSHARE",
                    "metadata": {},
                }
            )
        return records

    def _fetch_daily_frame(self, symbol, start_date: date, end_date: date) -> pd.DataFrame:
        """Fetch CN/HK forward-adjusted daily bars using AKShare's qfq mode."""
        import akshare as ak

        base = self._canonical_base(symbol.code)
        start = start_date.strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        try:
            if symbol.market == "CN":
                raw = ak.stock_zh_a_hist(
                    symbol=base,
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust="qfq",
                )
            elif symbol.market == "HK":
                raw = ak.stock_hk_hist(
                    symbol=base.zfill(5),
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust="qfq",
                )
            else:
                raise ValueError(f"AKShare daily history does not support market={symbol.market}")
            frame = self._normalize_data(raw, base)
        except Exception as exc:
            reason = str(exc)
            retryable = any(token in reason.lower() for token in ("timeout", "connection", "429", "rate", "频率"))
            raise RuntimeError(
                f"provider={self.name} market={symbol.market} code={symbol.code} "
                f"data_type=daily requested_range={start_date}..{end_date} retryable={retryable} reason={reason}"
            ) from exc
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        if symbol.market == "CN":
            # stock_zh_a_hist reports volume in lots (手); persist shares.
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") * 100.0
        columns = ["date", "open", "high", "low", "close", "volume", "amount"]
        return frame[columns].sort_values("date").reset_index(drop=True)

    def _set_random_user_agent(self) -> None:
        """
        设置随机 User-Agent

        通过修改 requests Session 的 headers 实现
        这是关键的反爬策略之一
        """
        try:
            import akshare as ak

            # akshare 内部使用 requests，我们通过环境变量或直接设置来影响
            # 实际上 akshare 可能不直接暴露 session，这里通过 fake_useragent 作为补充
            random_ua = random.choice(USER_AGENTS)
            logger.debug(f"设置 User-Agent: {random_ua[:50]}...")
        except Exception as e:
            logger.debug(f"设置 User-Agent 失败: {e}")

    def _enforce_rate_limit(self) -> None:
        """
        强制执行速率限制

        策略：
        1. 检查距离上次请求的时间间隔
        2. 如果间隔不足，补充休眠时间
        3. 然后再执行随机 jitter 休眠
        """
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            min_interval = self.sleep_min
            if elapsed < min_interval:
                additional_sleep = min_interval - elapsed
                logger.debug(f"补充休眠 {additional_sleep:.2f} 秒")
                time.sleep(additional_sleep)

        # 执行随机 jitter 休眠
        self.random_sleep(self.sleep_min, self.sleep_max)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),  # 最多重试3次
        wait=wait_exponential(multiplier=1, min=2, max=30),  # 指数退避：2, 4, 8... 最大30秒
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Akshare 获取原始数据

        根据代码类型自动选择 API：
        - 美股：不支持，抛出异常由 YFinanceProvider 处理（Issue #311）
        - 港股：使用 ak.stock_hk_hist()
        - ETF 基金：使用 ak.fund_etf_hist_em()
        - 普通 A 股：使用 ak.stock_zh_a_hist()

        流程：
        1. 判断代码类型（美股/港股/ETF/A股）
        2. 设置随机 User-Agent
        3. 执行速率限制（随机休眠）
        4. 调用对应的 akshare API
        5. 处理返回数据
        """
        # 根据代码类型选择不同的获取方法
        if is_us_code(stock_code):
            # 美股：akshare 的 stock_us_daily 接口复权存在已知问题（参见 Issue #311）
            # 交由 YFinanceProvider 处理，确保复权价格一致
            raise DataFetchError(f"AkShareProvider 不支持美股 {stock_code}，请使用 YFinanceProvider 获取正确的复权价格")
        elif is_hk_code(stock_code):
            return self._fetch_hk_data(stock_code, start_date, end_date)
        elif is_etf_code(stock_code):
            return self._fetch_etf_data(stock_code, start_date, end_date)
        else:
            return self._fetch_stock_data(stock_code, start_date, end_date)

    def _fetch_stock_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取普通 A 股历史数据

        策略：
        1. 优先尝试东方财富接口 (ak.stock_zh_a_hist)
        2. 失败后尝试新浪财经接口 (ak.stock_zh_a_daily)
        3. 最后尝试腾讯财经接口 (ak.stock_zh_a_hist_tx)
        """
        # 尝试列表
        methods = [
            (self._fetch_stock_data_em, "东方财富"),
            (self._fetch_stock_data_sina, "新浪财经"),
            (self._fetch_stock_data_tx, "腾讯财经"),
        ]

        last_error = None

        for fetch_method, source_name in methods:
            try:
                logger.info(f"[数据源] 尝试使用 {source_name} 获取 {stock_code}...")
                df = fetch_method(stock_code, start_date, end_date)

                if df is not None and not df.empty:
                    logger.info(f"[数据源] {source_name} 获取成功")
                    return df
            except Exception as e:
                last_error = e
                logger.warning(f"[数据源] {source_name} 获取失败: {e}")
                # 继续尝试下一个

        # 所有都失败
        raise DataFetchError(f"Akshare 所有渠道获取失败: {last_error}")

    def _fetch_stock_data_em(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取普通 A 股历史数据 (东方财富)
        数据来源：ak.stock_zh_a_hist()
        """
        import akshare as ak

        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()

        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()

        logger.info(f"[API调用] ak.stock_zh_a_hist(symbol={stock_code}, ...)")

        try:
            import time as _time

            api_start = _time.time()

            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )

            api_elapsed = _time.time() - api_start

            if df is not None and not df.empty:
                logger.info(f"[API返回] ak.stock_zh_a_hist 成功: {len(df)} 行, 耗时 {api_elapsed:.2f}s")
                return df
            else:
                logger.warning(f"[API返回] ak.stock_zh_a_hist 返回空数据")
                return pd.DataFrame()

        except Exception as e:
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["banned", "blocked", "频率", "rate", "限制"]):
                raise RateLimitError(f"Akshare(EM) 可能被限流: {e}") from e
            raise e

    def _fetch_stock_data_sina(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取普通 A 股历史数据 (新浪财经)
        数据来源：ak.stock_zh_a_daily()
        """
        import akshare as ak

        # 转换代码格式：sh600000, sz000001, bj920748
        symbol = to_sina_tx_symbol(stock_code)

        self._enforce_rate_limit()

        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""), adjust="qfq"
            )

            # 标准化新浪数据列名
            # 新浪返回：date, open, high, low, close, volume, amount, outstanding_share, turnover
            if df is not None and not df.empty:
                # 确保日期列存在
                if "date" in df.columns:
                    df = df.rename(columns={"date": "日期"})

                # 映射其他列以匹配 _normalize_data 的期望
                # _normalize_data 期望：日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额
                rename_map = {
                    "open": "开盘",
                    "high": "最高",
                    "low": "最低",
                    "close": "收盘",
                    "volume": "成交量",
                    "amount": "成交额",
                }
                df = df.rename(columns=rename_map)

                # 计算涨跌幅（新浪接口可能不返回）
                if "收盘" in df.columns:
                    df["涨跌幅"] = df["收盘"].pct_change() * 100
                    df["涨跌幅"] = df["涨跌幅"].fillna(0)

                return df
            return pd.DataFrame()

        except Exception as e:
            raise e

    def _fetch_stock_data_tx(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取普通 A 股历史数据 (腾讯财经)
        数据来源：ak.stock_zh_a_hist_tx()
        """
        import akshare as ak

        # 转换代码格式：sh600000, sz000001, bj920748
        symbol = to_sina_tx_symbol(stock_code)

        self._enforce_rate_limit()

        try:
            df = ak.stock_zh_a_hist_tx(
                symbol=symbol, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""), adjust="qfq"
            )

            # 标准化腾讯数据列名。AKShare 将腾讯第六列命名为 amount，
            # 但该列实际是成交量（例如股票日线为数万手），不是成交额。
            if df is not None and not df.empty:
                rename_map = {
                    "date": "日期",
                    "open": "开盘",
                    "high": "最高",
                    "low": "最低",
                    "close": "收盘",
                    "volume": "成交量",
                    "amount": "成交量",
                }
                df = df.rename(columns=rename_map)

                # 腾讯数据通常包含 '涨跌幅'，如果没有则计算
                if "pct_chg" in df.columns:
                    df = df.rename(columns={"pct_chg": "涨跌幅"})
                elif "收盘" in df.columns:
                    df["涨跌幅"] = df["收盘"].pct_change() * 100
                    df["涨跌幅"] = df["涨跌幅"].fillna(0)

                return df
            return pd.DataFrame()

        except Exception as e:
            raise e

    def _fetch_etf_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取 ETF 基金历史数据

        数据来源：ak.fund_etf_hist_em()

        Args:
            stock_code: ETF 代码，如 '512400', '159883'
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            ETF 历史数据 DataFrame
        """
        import akshare as ak

        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()

        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()

        logger.info(
            f"[API调用] ak.fund_etf_hist_em(symbol={stock_code}, period=daily, "
            f"start_date={start_date.replace('-', '')}, end_date={end_date.replace('-', '')}, adjust=qfq)"
        )

        try:
            import time as _time

            api_start = _time.time()

            # 调用 akshare 获取 ETF 日线数据
            df = ak.fund_etf_hist_em(
                symbol=stock_code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",  # 前复权
            )

            api_elapsed = _time.time() - api_start

            # 记录返回数据摘要
            if df is not None and not df.empty:
                logger.info(f"[API返回] ak.fund_etf_hist_em 成功: 返回 {len(df)} 行数据, 耗时 {api_elapsed:.2f}s")
                logger.info(f"[API返回] 列名: {list(df.columns)}")
                logger.info(f"[API返回] 日期范围: {df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
                logger.debug(f"[API返回] 最新3条数据:\n{df.tail(3).to_string()}")
            else:
                logger.warning(f"[API返回] ak.fund_etf_hist_em 返回空数据, 耗时 {api_elapsed:.2f}s")

            return df

        except Exception as e:
            error_msg = str(e).lower()

            # 检测反爬封禁
            if any(keyword in error_msg for keyword in ["banned", "blocked", "频率", "rate", "限制"]):
                logger.warning(f"检测到可能被封禁: {e}")
                raise RateLimitError(f"Akshare 可能被限流: {e}") from e

            raise DataFetchError(f"Akshare 获取 ETF 数据失败: {e}") from e

    def _fetch_us_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取美股历史数据

        数据来源：ak.stock_us_daily()（新浪财经接口）

        Args:
            stock_code: 美股代码，如 'AMD', 'AAPL', 'TSLA'
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            美股历史数据 DataFrame
        """
        import akshare as ak

        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()

        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()

        # 美股代码直接使用大写
        symbol = stock_code.strip().upper()

        logger.info(f"[API调用] ak.stock_us_daily(symbol={symbol}, adjust=qfq)")

        try:
            import time as _time

            api_start = _time.time()

            # 调用 akshare 获取美股日线数据
            # stock_us_daily 返回全部历史数据，后续需要按日期过滤
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")  # 前复权

            api_elapsed = _time.time() - api_start

            # 记录返回数据摘要
            if df is not None and not df.empty:
                logger.info(f"[API返回] ak.stock_us_daily 成功: 返回 {len(df)} 行数据, 耗时 {api_elapsed:.2f}s")
                logger.info(f"[API返回] 列名: {list(df.columns)}")

                # 按日期过滤
                df["date"] = pd.to_datetime(df["date"])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

                if not df.empty:
                    logger.info(
                        f"[API返回] 过滤后日期范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}"
                    )
                    logger.debug(f"[API返回] 最新3条数据:\n{df.tail(3).to_string()}")
                else:
                    logger.warning(f"[API返回] 过滤后数据为空，日期范围 {start_date} ~ {end_date} 无数据")

                # 转换列名为中文格式以匹配 _normalize_data
                # stock_us_daily 返回: date, open, high, low, close, volume
                rename_map = {
                    "date": "日期",
                    "open": "开盘",
                    "high": "最高",
                    "low": "最低",
                    "close": "收盘",
                    "volume": "成交量",
                }
                df = df.rename(columns=rename_map)

                # 计算涨跌幅（美股接口不直接返回）
                if "收盘" in df.columns:
                    df["涨跌幅"] = df["收盘"].pct_change() * 100
                    df["涨跌幅"] = df["涨跌幅"].fillna(0)

                # 估算成交额（美股接口不返回）
                if "成交量" in df.columns and "收盘" in df.columns:
                    df["成交额"] = df["成交量"] * df["收盘"]
                else:
                    df["成交额"] = 0

                return df
            else:
                logger.warning(f"[API返回] ak.stock_us_daily 返回空数据, 耗时 {api_elapsed:.2f}s")
                return pd.DataFrame()

        except Exception as e:
            error_msg = str(e).lower()

            # 检测反爬封禁
            if any(keyword in error_msg for keyword in ["banned", "blocked", "频率", "rate", "限制"]):
                logger.warning(f"检测到可能被封禁: {e}")
                raise RateLimitError(f"Akshare 可能被限流: {e}") from e

            raise DataFetchError(f"Akshare 获取美股数据失败: {e}") from e

    def _fetch_hk_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取港股历史数据

        数据来源：ak.stock_hk_hist()

        Args:
            stock_code: 港股代码，如 '00700', '01810'
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            港股历史数据 DataFrame
        """
        import akshare as ak

        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()

        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()

        # 确保代码格式正确（5位数字）
        code = stock_code.lower().replace("hk", "").zfill(5)

        logger.info(
            f"[API调用] ak.stock_hk_hist(symbol={code}, period=daily, "
            f"start_date={start_date.replace('-', '')}, end_date={end_date.replace('-', '')}, adjust=qfq)"
        )

        try:
            import time as _time

            api_start = _time.time()

            # 调用 akshare 获取港股日线数据
            df = ak.stock_hk_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",  # 前复权
            )

            api_elapsed = _time.time() - api_start

            # 记录返回数据摘要
            if df is not None and not df.empty:
                logger.info(f"[API返回] ak.stock_hk_hist 成功: 返回 {len(df)} 行数据, 耗时 {api_elapsed:.2f}s")
                logger.info(f"[API返回] 列名: {list(df.columns)}")
                logger.info(f"[API返回] 日期范围: {df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
                logger.debug(f"[API返回] 最新3条数据:\n{df.tail(3).to_string()}")
            else:
                logger.warning(f"[API返回] ak.stock_hk_hist 返回空数据, 耗时 {api_elapsed:.2f}s")

            return df

        except Exception as e:
            error_msg = str(e).lower()

            # 检测反爬封禁
            if any(keyword in error_msg for keyword in ["banned", "blocked", "频率", "rate", "限制"]):
                logger.warning(f"检测到可能被封禁: {e}")
                raise RateLimitError(f"Akshare 可能被限流: {e}") from e

            raise DataFetchError(f"Akshare 获取港股数据失败: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Akshare 数据

        Akshare 返回的列名（中文）：
        日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率

        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        if df is None or df.empty:
            return pd.DataFrame(columns=["code"] + STANDARD_COLUMNS)

        df = df.copy()

        # 列名映射（Akshare 中文列名 -> 标准英文列名）
        column_mapping = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
        }

        # 重命名列
        df = df.rename(columns=column_mapping)

        required_columns = {"date", "open", "high", "low", "close", "volume"}
        missing = sorted(required_columns.difference(df.columns))
        if missing:
            raise DataFetchError(f"Akshare 历史行情缺少必要字段: {', '.join(missing)}")

        # Upstream endpoints do not all expose turnover or percentage change.
        # Keep a stable provider schema without fabricating either value.
        for column in ("amount", "pct_chg"):
            if column not in df.columns:
                df[column] = pd.NA

        # 添加股票代码列
        df["code"] = stock_code

        # 只保留需要的列
        keep_cols = ["code"] + STANDARD_COLUMNS
        df = df[keep_cols]

        return df

    def get_realtime_quote(self, stock_code: str, source: str = "em") -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情数据（支持多数据源）

        数据源优先级（可配置）：
        1. em: 东方财富（akshare ak.stock_zh_a_spot_em）- 数据最全，含量比/PE/PB/市值等
        2. sina: 新浪财经（akshare ak.stock_zh_a_spot）- 轻量级，基本行情
        3. tencent: 腾讯直连接口 - 单股票查询，负载小

        Args:
            stock_code: 股票/ETF代码
            source: 数据源类型，可选 "em", "sina", "tencent"

        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        circuit_breaker = get_realtime_circuit_breaker()

        # 根据代码类型选择不同的获取方法
        if is_us_code(stock_code):
            # 美股不使用 Akshare，由 YFinanceProvider 处理
            logger.debug(f"[API跳过] {stock_code} 是美股，Akshare 不支持美股实时行情")
            return None
        elif is_hk_code(stock_code):
            return self._get_hk_realtime_quote(stock_code)
        elif is_etf_code(stock_code):
            source_key = "akshare_etf"
            if not circuit_breaker.is_available(source_key):
                logger.info(f"[熔断] 数据源 {source_key} 处于熔断状态，跳过")
                return None
            return self._get_etf_realtime_quote(stock_code)
        else:
            source_key = f"akshare_{source}"
            if not circuit_breaker.is_available(source_key):
                logger.info(f"[熔断] 数据源 {source_key} 处于熔断状态，跳过")
                return None
            # 普通 A 股：根据 source 选择数据源
            if source == "sina":
                return self._get_stock_realtime_quote_sina(stock_code)
            elif source == "tencent":
                return self._get_stock_realtime_quote_tencent(stock_code)
            else:
                return self._get_stock_realtime_quote_em(stock_code)

    def _get_stock_realtime_quote_em(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（东方财富数据源）

        数据来源：ak.stock_zh_a_spot_em()
        优点：数据最全，含量比、换手率、市盈率、市净率、总市值、流通市值等
        缺点：全量拉取，数据量大，容易超时/限流
        """
        import akshare as ak

        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_em"

        try:
            # 检查缓存
            current_time = time.time()
            if (
                _realtime_cache["data"] is not None
                and current_time - _realtime_cache["timestamp"] < _realtime_cache["ttl"]
            ):
                df = _realtime_cache["data"]
                cache_age = int(current_time - _realtime_cache["timestamp"])
                logger.debug(f"[缓存命中] A股实时行情(东财) - 缓存年龄 {cache_age}s/{_realtime_cache['ttl']}s")
            else:
                # 触发全量刷新
                logger.info(f"[缓存未命中] 触发全量刷新 A股实时行情(东财)")
                last_error: Optional[Exception] = None
                df = None
                for attempt in range(1, 3):
                    try:
                        # 防封禁策略
                        self._set_random_user_agent()
                        self._enforce_rate_limit()

                        logger.info(f"[API调用] ak.stock_zh_a_spot_em() 获取A股实时行情... (attempt {attempt}/2)")
                        import time as _time

                        api_start = _time.time()

                        df = ak.stock_zh_a_spot_em()

                        api_elapsed = _time.time() - api_start
                        logger.info(
                            f"[API返回] ak.stock_zh_a_spot_em 成功: 返回 {len(df)} 只股票, 耗时 {api_elapsed:.2f}s"
                        )
                        circuit_breaker.record_success(source_key)
                        break
                    except Exception as e:
                        last_error = e
                        logger.info(f"[API错误] ak.stock_zh_a_spot_em 获取失败 (attempt {attempt}/2): {e}")
                        time.sleep(min(2**attempt, 5))

                # 更新缓存：成功缓存数据；失败也缓存空数据，避免同一轮任务对同一接口反复请求
                if df is None:
                    logger.info(f"[API错误] ak.stock_zh_a_spot_em 最终失败: {last_error}")
                    circuit_breaker.record_failure(source_key, str(last_error))
                    df = pd.DataFrame()
                _realtime_cache["data"] = df
                _realtime_cache["timestamp"] = current_time
                logger.info(f"[缓存更新] A股实时行情(东财) 缓存已刷新，TTL={_realtime_cache['ttl']}s")

            if df is None or df.empty:
                logger.info(f"[实时行情] A股实时行情数据为空，跳过 {stock_code}")
                return None

            # 查找指定股票
            row = df[df["代码"] == stock_code]
            if row.empty:
                logger.info(f"[API返回] 未找到股票 {stock_code} 的实时行情")
                return None

            row = row.iloc[0]

            # 使用 realtime_types.py 中的统一转换函数
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get("名称", "")),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get("最新价")),
                change_pct=safe_float(row.get("涨跌幅")),
                change_amount=safe_float(row.get("涨跌额")),
                volume=safe_int(row.get("成交量")),
                amount=safe_float(row.get("成交额")),
                volume_ratio=safe_float(row.get("量比")),
                turnover_rate=safe_float(row.get("换手率")),
                amplitude=safe_float(row.get("振幅")),
                open_price=safe_float(row.get("今开")),
                high=safe_float(row.get("最高")),
                low=safe_float(row.get("最低")),
                pe_ratio=safe_float(row.get("市盈率-动态")),
                pb_ratio=safe_float(row.get("市净率")),
                total_mv=safe_float(row.get("总市值")),
                circ_mv=safe_float(row.get("流通市值")),
                change_60d=safe_float(row.get("60日涨跌幅")),
                high_52w=safe_float(row.get("52周最高")),
                low_52w=safe_float(row.get("52周最低")),
            )

            logger.info(
                f"[实时行情-东财] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                f"量比={quote.volume_ratio}, 换手率={quote.turnover_rate}%"
            )
            return quote

        except Exception as e:
            logger.info(f"[API错误] 获取 {stock_code} 实时行情(东财)失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None

    def _get_stock_realtime_quote_sina(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（新浪财经数据源）

        数据来源：新浪财经接口（直连，单股票查询）
        优点：单股票查询，负载小，速度快
        缺点：数据字段较少，无量比/PE/PB等

        接口格式：http://hq.sinajs.cn/list=sh600519,sz000001
        """
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_sina"
        symbol = to_sina_tx_symbol(stock_code)
        url = f"http://{SINA_REALTIME_ENDPOINT}={symbol}"
        api_start = time.time()

        try:
            headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": random.choice(USER_AGENTS)}

            logger.info(
                f"[API调用] 新浪财经接口获取 {stock_code} 实时行情: endpoint={SINA_REALTIME_ENDPOINT}, symbol={symbol}"
            )

            self._enforce_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = "gbk"
            api_elapsed = time.time() - api_start

            if response.status_code != 200:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="http_status",
                    detail=f"HTTP {response.status_code}",
                    elapsed=api_elapsed,
                    error_type="HTTPStatus",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            # 解析数据：var hq_str_sh600519="贵州茅台,1866.000,1870.000,..."
            content = response.text.strip()
            if '=""' in content or not content:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="empty_response",
                    detail="empty quote payload",
                    elapsed=api_elapsed,
                    error_type="EmptyResponse",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            # 提取引号内的数据
            data_start = content.find('"')
            data_end = content.rfind('"')
            if data_start == -1 or data_end == -1:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="malformed_payload",
                    detail="quote payload missing quotes",
                    elapsed=api_elapsed,
                    error_type="MalformedPayload",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            data_str = content[data_start + 1 : data_end]
            fields = data_str.split(",")

            if len(fields) < 32:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="insufficient_fields",
                    detail=f"field_count={len(fields)}",
                    elapsed=api_elapsed,
                    error_type="InsufficientFields",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            circuit_breaker.record_success(source_key)

            # 新浪数据字段顺序：
            # 0:名称 1:今开 2:昨收 3:最新价 4:最高 5:最低 6:买一价 7:卖一价
            # 8:成交量(股) 9:成交额(元) ... 30:日期 31:时间
            # 使用 realtime_types.py 中的统一转换函数
            price = safe_float(fields[3])
            pre_close = safe_float(fields[2])
            change_pct = None
            change_amount = None
            if price and pre_close and pre_close > 0:
                change_amount = price - pre_close
                change_pct = (change_amount / pre_close) * 100

            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=fields[0],
                source=RealtimeSource.AKSHARE_SINA,
                price=price,
                change_pct=change_pct,
                change_amount=change_amount,
                volume=safe_int(fields[8]),  # 成交量（股）
                amount=safe_float(fields[9]),  # 成交额（元）
                open_price=safe_float(fields[1]),
                high=safe_float(fields[4]),
                low=safe_float(fields[5]),
                pre_close=pre_close,
            )

            logger.info(
                f"[实时行情-新浪] {stock_code} {quote.name}: endpoint={SINA_REALTIME_ENDPOINT}, "
                f"价格={quote.price}, 涨跌={quote.change_pct}, 成交量={quote.volume}, elapsed={api_elapsed:.2f}s"
            )
            return quote

        except Exception as e:
            api_elapsed = time.time() - api_start
            category, detail = _classify_realtime_http_error(e)
            failure_message = _build_realtime_failure_message(
                source_name="新浪",
                endpoint=SINA_REALTIME_ENDPOINT,
                stock_code=stock_code,
                symbol=symbol,
                category=category,
                detail=detail,
                elapsed=api_elapsed,
                error_type=type(e).__name__,
            )
            logger.info(failure_message)
            circuit_breaker.record_failure(source_key, failure_message)
            return None

    def _get_stock_realtime_quote_tencent(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（腾讯财经数据源）

        数据来源：腾讯财经接口（直连，单股票查询）
        优点：单股票查询，负载小，包含换手率
        缺点：无量比/PE/PB等估值数据

        接口格式：http://qt.gtimg.cn/q=sh600519,sz000001
        """
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_tencent"
        symbol = to_sina_tx_symbol(stock_code)
        url = f"http://{TENCENT_REALTIME_ENDPOINT}={symbol}"
        api_start = time.time()

        try:
            headers = {"Referer": "http://finance.qq.com", "User-Agent": random.choice(USER_AGENTS)}

            logger.info(
                f"[API调用] 腾讯财经接口获取 {stock_code} 实时行情: endpoint={TENCENT_REALTIME_ENDPOINT}, symbol={symbol}"
            )

            self._enforce_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = "gbk"
            api_elapsed = time.time() - api_start

            if response.status_code != 200:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="http_status",
                    detail=f"HTTP {response.status_code}",
                    elapsed=api_elapsed,
                    error_type="HTTPStatus",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            content = response.text.strip()
            if '=""' in content or not content:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="empty_response",
                    detail="empty quote payload",
                    elapsed=api_elapsed,
                    error_type="EmptyResponse",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            # 提取数据
            data_start = content.find('"')
            data_end = content.rfind('"')
            if data_start == -1 or data_end == -1:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="malformed_payload",
                    detail="quote payload missing quotes",
                    elapsed=api_elapsed,
                    error_type="MalformedPayload",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            data_str = content[data_start + 1 : data_end]
            fields = data_str.split("~")

            if len(fields) < 45:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="insufficient_fields",
                    detail=f"field_count={len(fields)}",
                    elapsed=api_elapsed,
                    error_type="InsufficientFields",
                )
                logger.info(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None

            circuit_breaker.record_success(source_key)

            # 腾讯数据字段顺序（完整）：
            # 1:名称 2:代码 3:最新价 4:昨收 5:今开 6:成交量(手) 7:外盘 8:内盘
            # 9-28:买卖五档 30:时间戳 31:涨跌额 32:涨跌幅(%) 33:最高 34:最低 35:收盘/成交量/成交额
            # 36:成交量(手) 37:成交额(万) 38:换手率(%) 39:市盈率 43:振幅(%)
            # 44:流通市值(亿) 45:总市值(亿) 46:市净率 47:涨停价 48:跌停价 49:量比
            # 使用 realtime_types.py 中的统一转换函数
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=fields[1] if len(fields) > 1 else "",
                source=RealtimeSource.TENCENT,
                price=safe_float(fields[3]),
                change_pct=safe_float(fields[32]),
                change_amount=safe_float(fields[31]) if len(fields) > 31 else None,
                volume=safe_int(fields[6]) * 100 if fields[6] else None,  # 腾讯返回的是手，转为股
                open_price=safe_float(fields[5]),
                high=safe_float(fields[33]) if len(fields) > 33 else None,  # 修正：字段 33 是最高价
                low=safe_float(fields[34]) if len(fields) > 34 else None,  # 修正：字段 34 是最低价
                pre_close=safe_float(fields[4]),
                turnover_rate=safe_float(fields[38]) if len(fields) > 38 else None,
                amplitude=safe_float(fields[43]) if len(fields) > 43 else None,
                volume_ratio=safe_float(fields[49]) if len(fields) > 49 else None,  # 量比
                pe_ratio=safe_float(fields[39]) if len(fields) > 39 else None,  # 市盈率
                pb_ratio=safe_float(fields[46]) if len(fields) > 46 else None,  # 市净率
                circ_mv=(
                    safe_float(fields[44]) * 100000000 if len(fields) > 44 and fields[44] else None
                ),  # 流通市值(亿->元)
                total_mv=(
                    safe_float(fields[45]) * 100000000 if len(fields) > 45 and fields[45] else None
                ),  # 总市值(亿->元)
            )

            logger.info(
                f"[实时行情-腾讯] {stock_code} {quote.name}: endpoint={TENCENT_REALTIME_ENDPOINT}, "
                f"价格={quote.price}, 涨跌={quote.change_pct}%, 量比={quote.volume_ratio}, "
                f"换手率={quote.turnover_rate}%, elapsed={api_elapsed:.2f}s"
            )
            return quote

        except Exception as e:
            api_elapsed = time.time() - api_start
            category, detail = _classify_realtime_http_error(e)
            failure_message = _build_realtime_failure_message(
                source_name="腾讯",
                endpoint=TENCENT_REALTIME_ENDPOINT,
                stock_code=stock_code,
                symbol=symbol,
                category=category,
                detail=detail,
                elapsed=api_elapsed,
                error_type=type(e).__name__,
            )
            logger.info(failure_message)
            circuit_breaker.record_failure(source_key, failure_message)
            return None

    def _get_etf_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取 ETF 基金实时行情数据

        数据来源：ak.fund_etf_spot_em()
        包含：最新价、涨跌幅、成交量、成交额、换手率等

        Args:
            stock_code: ETF 代码

        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        import akshare as ak

        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_etf"

        try:
            # 检查缓存
            current_time = time.time()
            if (
                _etf_realtime_cache["data"] is not None
                and current_time - _etf_realtime_cache["timestamp"] < _etf_realtime_cache["ttl"]
            ):
                df = _etf_realtime_cache["data"]
                logger.debug(f"[缓存命中] 使用缓存的ETF实时行情数据")
            else:
                last_error: Optional[Exception] = None
                df = None
                for attempt in range(1, 3):
                    try:
                        # 防封禁策略
                        self._set_random_user_agent()
                        self._enforce_rate_limit()

                        logger.info(f"[API调用] ak.fund_etf_spot_em() 获取ETF实时行情... (attempt {attempt}/2)")
                        import time as _time

                        api_start = _time.time()

                        df = ak.fund_etf_spot_em()

                        api_elapsed = _time.time() - api_start
                        logger.info(
                            f"[API返回] ak.fund_etf_spot_em 成功: 返回 {len(df)} 只ETF, 耗时 {api_elapsed:.2f}s"
                        )
                        circuit_breaker.record_success(source_key)
                        break
                    except Exception as e:
                        last_error = e
                        logger.info(f"[API错误] ak.fund_etf_spot_em 获取失败 (attempt {attempt}/2): {e}")
                        time.sleep(min(2**attempt, 5))

                if df is None:
                    logger.info(f"[API错误] ak.fund_etf_spot_em 最终失败: {last_error}")
                    circuit_breaker.record_failure(source_key, str(last_error))
                    df = pd.DataFrame()
                _etf_realtime_cache["data"] = df
                _etf_realtime_cache["timestamp"] = current_time

            if df is None or df.empty:
                logger.info(f"[实时行情] ETF实时行情数据为空，跳过 {stock_code}")
                return None

            # 查找指定 ETF
            row = df[df["代码"] == stock_code]
            if row.empty:
                logger.info(f"[API返回] 未找到 ETF {stock_code} 的实时行情")
                return None

            row = row.iloc[0]

            # 使用 realtime_types.py 中的统一转换函数
            # ETF 行情数据构建
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get("名称", "")),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get("最新价")),
                change_pct=safe_float(row.get("涨跌幅")),
                change_amount=safe_float(row.get("涨跌额")),
                volume=safe_int(row.get("成交量")),
                amount=safe_float(row.get("成交额")),
                volume_ratio=safe_float(row.get("量比")),
                turnover_rate=safe_float(row.get("换手率")),
                amplitude=safe_float(row.get("振幅")),
                open_price=safe_float(row.get("开盘价")),
                high=safe_float(row.get("最高价")),
                low=safe_float(row.get("最低价")),
                total_mv=safe_float(row.get("总市值")),
                circ_mv=safe_float(row.get("流通市值")),
                high_52w=safe_float(row.get("52周最高")),
                low_52w=safe_float(row.get("52周最低")),
            )

            logger.info(
                f"[ETF实时行情] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                f"换手率={quote.turnover_rate}%"
            )
            return quote

        except Exception as e:
            logger.info(f"[API错误] 获取 ETF {stock_code} 实时行情失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None

    def _get_hk_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取港股实时行情数据

        主数据源：ak.stock_hk_spot_em()（东方财富）
        备用数据源：ak.stock_hk_spot()（新浪）
        包含：最新价、涨跌幅、成交量、成交额等

        Args:
            stock_code: 港股代码

        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        import akshare as ak

        circuit_breaker = get_realtime_circuit_breaker()
        em_key = "akshare_hk_em"
        sina_key = "akshare_hk_sina"

        # 防封禁策略
        self._set_random_user_agent()
        self._enforce_rate_limit()

        # 确保代码格式正确（5位数字）
        raw_code = stock_code.strip().lower()
        if raw_code.endswith(".hk"):
            raw_code = raw_code[:-3]
        if raw_code.startswith("hk"):
            raw_code = raw_code[2:]
        code = raw_code.zfill(5)

        # --- 主数据源：东方财富 ---
        if circuit_breaker.is_available(em_key):
            try:
                logger.info(f"[API调用] ak.stock_hk_spot_em() 获取港股实时行情...")
                import time as _time

                api_start = _time.time()

                df = ak.stock_hk_spot_em()

                api_elapsed = _time.time() - api_start
                logger.info(f"[API返回] ak.stock_hk_spot_em 成功: 返回 {len(df)} 只港股, 耗时 {api_elapsed:.2f}s")
                circuit_breaker.record_success(em_key)

                # 查找指定港股
                row = df[df["代码"] == code]
                if row.empty:
                    logger.info(f"[API返回] 未找到港股 {code} 的实时行情 (stock_hk_spot_em)")
                else:
                    row = row.iloc[0]
                    quote = UnifiedRealtimeQuote(
                        code=stock_code,
                        name=str(row.get("名称", "")),
                        source=RealtimeSource.AKSHARE_EM,
                        price=safe_float(row.get("最新价")),
                        change_pct=safe_float(row.get("涨跌幅")),
                        change_amount=safe_float(row.get("涨跌额")),
                        volume=safe_int(row.get("成交量")),
                        amount=safe_float(row.get("成交额")),
                        volume_ratio=safe_float(row.get("量比")),
                        turnover_rate=safe_float(row.get("换手率")),
                        amplitude=safe_float(row.get("振幅")),
                        pe_ratio=safe_float(row.get("市盈率")),
                        pb_ratio=safe_float(row.get("市净率")),
                        total_mv=safe_float(row.get("总市值")),
                        circ_mv=safe_float(row.get("流通市值")),
                        high_52w=safe_float(row.get("52周最高")),
                        low_52w=safe_float(row.get("52周最低")),
                    )
                    logger.info(
                        f"[港股实时行情] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                        f"换手率={quote.turnover_rate}%"
                    )
                    return quote

            except Exception as e:
                logger.warning(
                    f"[API错误] ak.stock_hk_spot_em 获取港股 {stock_code} 失败: {e}，尝试 stock_hk_spot 备用接口"
                )
                circuit_breaker.record_failure(em_key, str(e))
        else:
            logger.info(f"[熔断] 数据源 {em_key} 处于熔断状态，尝试使用备用链路")

        # --- 备用数据源：新浪 ---
        if not circuit_breaker.is_available(sina_key):
            logger.info(f"[熔断] 数据源 {sina_key} 处于熔断状态，跳过备用链路")
            return None

        try:
            logger.info(f"[API调用] ak.stock_hk_spot() 获取港股实时行情（备用）...")
            import time as _time

            api_start = _time.time()

            df_spot = ak.stock_hk_spot()

            api_elapsed = _time.time() - api_start
            logger.info(f"[API返回] ak.stock_hk_spot 成功: 返回 {len(df_spot)} 只港股, 耗时 {api_elapsed:.2f}s")

            row = df_spot[df_spot["代码"] == code]
            if row.empty:
                logger.info(f"[API返回] 未找到港股 {code} 的实时行情 (stock_hk_spot)")
                return None

            row = row.iloc[0]
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get("名称", "")),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get("最新价")),
                change_pct=safe_float(row.get("涨跌幅")),
                change_amount=safe_float(row.get("涨跌额")),
                volume=safe_int(row.get("成交量")),
                amount=safe_float(row.get("成交额")),
            )
            circuit_breaker.record_success(sina_key)
            logger.info(f"[港股实时行情-备用] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%")
            return quote

        except Exception as e:
            logger.info(f"[API错误] ak.stock_hk_spot 备用接口也失败: {e}")
            circuit_breaker.record_failure(sina_key, str(e))
            return None

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        获取筹码分布数据

        数据来源：ak.stock_cyq_em()
        包含：获利比例、平均成本、筹码集中度

        注意：ETF/指数没有筹码分布数据，会直接返回 None

        Args:
            stock_code: 股票代码

        Returns:
            ChipDistribution 对象（最新一天的数据），获取失败返回 None
        """
        import akshare as ak

        # 美股没有筹码分布数据（Akshare 不支持）
        if is_us_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是美股，无筹码分布数据")
            return None

        # 港股没有筹码分布数据（stock_cyq_em 是 A 股专属接口）
        if is_hk_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是港股，无筹码分布数据")
            return None

        # ETF/指数没有筹码分布数据
        if is_etf_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是 ETF/指数，无筹码分布数据")
            return None

        try:
            # 防封禁策略
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info(f"[API调用] ak.stock_cyq_em(symbol={stock_code}) 获取筹码分布...")
            import time as _time

            api_start = _time.time()

            df = ak.stock_cyq_em(symbol=stock_code)

            api_elapsed = _time.time() - api_start

            if df.empty:
                logger.warning(f"[API返回] ak.stock_cyq_em 返回空数据, 耗时 {api_elapsed:.2f}s")
                return None

            logger.info(f"[API返回] ak.stock_cyq_em 成功: 返回 {len(df)} 天数据, 耗时 {api_elapsed:.2f}s")
            logger.debug(f"[API返回] 筹码数据列名: {list(df.columns)}")

            # 取最新一天的数据
            latest = df.iloc[-1]

            # 使用 realtime_types.py 中的统一转换函数
            chip = ChipDistribution(
                code=stock_code,
                date=str(latest.get("日期", "")),
                profit_ratio=safe_float(latest.get("获利比例")),
                avg_cost=safe_float(latest.get("平均成本")),
                cost_90_low=safe_float(latest.get("90成本-低")),
                cost_90_high=safe_float(latest.get("90成本-高")),
                concentration_90=safe_float(latest.get("90集中度")),
                cost_70_low=safe_float(latest.get("70成本-低")),
                cost_70_high=safe_float(latest.get("70成本-高")),
                concentration_70=safe_float(latest.get("70集中度")),
            )

            logger.info(
                f"[筹码分布] {stock_code} 日期={chip.date}: 获利比例={chip.profit_ratio:.1%}, "
                f"平均成本={chip.avg_cost}, 90%集中度={chip.concentration_90:.2%}, "
                f"70%集中度={chip.concentration_70:.2%}"
            )
            return chip

        except Exception as e:
            logger.exception(f"[API错误] 获取 {stock_code} 筹码分布失败: {e}")
            return None

    def _get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数实时行情 (新浪接口)，仅支持 A 股
        """
        if region != "cn":
            return None
        import akshare as ak

        # 主要指数代码映射
        indices_map = {
            "sh000001": "上证指数",
            "sz399001": "深证成指",
            "sz399006": "创业板指",
            "sh000688": "科创50",
            "sh000016": "上证50",
            "sh000300": "沪深300",
        }

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            # 使用 akshare 获取指数行情（新浪财经接口）
            df = ak.stock_zh_index_spot_sina()

            results = []
            if df is not None and not df.empty:
                for code, name in indices_map.items():
                    # 查找对应指数
                    row = df[df["代码"] == code]
                    if row.empty:
                        # 尝试带前缀查找
                        row = df[df["代码"].str.contains(code)]

                    if not row.empty:
                        row = row.iloc[0]
                        current = safe_float(row.get("最新价", 0))
                        prev_close = safe_float(row.get("昨收", 0))
                        high = safe_float(row.get("最高", 0))
                        low = safe_float(row.get("最低", 0))

                        # 计算振幅
                        amplitude = 0.0
                        if prev_close > 0:
                            amplitude = (high - low) / prev_close * 100

                        results.append(
                            {
                                "code": code,
                                "name": name,
                                "current": current,
                                "change": safe_float(row.get("涨跌额", 0)),
                                "change_pct": safe_float(row.get("涨跌幅", 0)),
                                "open": safe_float(row.get("今开", 0)),
                                "high": high,
                                "low": low,
                                "prev_close": prev_close,
                                "volume": safe_float(row.get("成交量", 0)),
                                "amount": safe_float(row.get("成交额", 0)),
                                "amplitude": amplitude,
                            }
                        )
            return results

        except Exception as e:
            logger.exception(f"[Akshare] 获取指数行情失败: {e}")
            return None

    def _get_market_stats(self) -> Optional[Dict[str, Any]]:
        """
        获取市场涨跌统计

        数据源优先级：
        1. 东财接口 (ak.stock_zh_a_spot_em)
        2. 新浪接口 (ak.stock_zh_a_spot)
        """
        import akshare as ak

        # 优先东财接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_zh_a_spot_em() 获取市场统计...")
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                return self._calc_market_stats(df)
        except Exception as e:
            logger.warning(f"[Akshare] 东财接口获取市场统计失败: {e}，尝试新浪接口")

        # 东财失败后，尝试新浪接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_zh_a_spot() 获取市场统计(新浪)...")
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                return self._calc_market_stats(df)
        except Exception as e:
            logger.exception(f"[Akshare] 新浪接口获取市场统计也失败: {e}")

        return None

    def _calc_market_stats(
        self,
        df: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        """从行情 DataFrame 计算涨跌统计。"""
        import numpy as np

        df = df.copy()

        # 1. 提取基础比对数据：最新价、昨收
        # 兼容不同接口返回的列名 sina/em efinance xtdata
        code_col = next((c for c in ["代码", "股票代码", "ts_code", "stock_code"] if c in df.columns), None)
        name_col = next((c for c in ["名称", "股票名称", "name", "name"] if c in df.columns), None)
        close_col = next((c for c in ["最新价", "最新价", "close", "lastPrice"] if c in df.columns), None)
        pre_close_col = next((c for c in ["昨收", "昨日收盘", "pre_close", "lastClose"] if c in df.columns), None)
        amount_col = next((c for c in ["成交额", "成交额", "amount", "amount"] if c in df.columns), None)

        required = {
            "code": code_col,
            "name": name_col,
            "close": close_col,
            "pre_close": pre_close_col,
            "amount": amount_col,
        }
        missing = [name for name, column in required.items() if column is None]
        if missing:
            logger.warning("[Akshare] 行情统计缺少必要字段: %s", ", ".join(missing))
            return None

        limit_up_count = 0
        limit_down_count = 0
        up_count = 0
        down_count = 0
        flat_count = 0

        for code, name, current_price, pre_close, amount in zip(
            df[code_col], df[name_col], df[close_col], df[pre_close_col], df[amount_col]
        ):

            # 停牌过滤 efinance 的停牌数据有时候会缺失价格显示为 '-'，em 显示为none
            if (
                pd.isna(current_price)
                or pd.isna(pre_close)
                or current_price in ["-"]
                or pre_close in ["-"]
                or amount == 0
            ):
                continue

            # em、efinance 为str 需要转换为float
            current_price = float(current_price)
            pre_close = float(pre_close)

            # 获取去除前缀的纯数字代码
            pure_code = normalize_stock_code(str(code))

            # A. 确定每只股票的涨跌幅比例 (使用纯数字代码判断)
            if is_bse_code(pure_code):
                ratio = 0.30
            elif is_kc_cy_stock(pure_code):  # pure_code.startswith(('688', '30')):
                ratio = 0.20
            elif is_st_stock(name):  #'ST' in str_name:
                ratio = 0.05
            else:
                ratio = 0.10

            # B. 严格按照 A 股规则计算涨跌停价：昨收 * (1 ± 比例) -> 四舍五入保留2位小数
            limit_up_price = np.floor(pre_close * (1 + ratio) * 100 + 0.5) / 100.0
            limit_down_price = np.floor(pre_close * (1 - ratio) * 100 + 0.5) / 100.0

            limit_up_price_Tolerance = round(abs(pre_close * (1 + ratio) - limit_up_price), 10)
            limit_down_price_Tolerance = round(abs(pre_close * (1 - ratio) - limit_down_price), 10)

            # C. 精确比对
            if current_price > 0:
                is_limit_up = (current_price > 0) and (abs(current_price - limit_up_price) <= limit_up_price_Tolerance)
                is_limit_down = (current_price > 0) and (
                    abs(current_price - limit_down_price) <= limit_down_price_Tolerance
                )

                if is_limit_up:
                    limit_up_count += 1
                if is_limit_down:
                    limit_down_count += 1

                if current_price > pre_close:
                    up_count += 1
                elif current_price < pre_close:
                    down_count += 1
                else:
                    flat_count += 1

        # 统计数量
        stats = {
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "total_amount": 0.0,
        }

        # 成交额统计
        if amount_col and amount_col in df.columns:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce")
            stats["total_amount"] = df[amount_col].sum() / 1e8

        return stats

    def _get_sector_rankings(self, n: int = 20) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """
        获取行业板块涨跌榜

        数据源优先级：
        1. 东财接口 (ak.stock_board_industry_name_em)
        2. 新浪接口 (ak.stock_sector_spot)
        """
        import akshare as ak

        def _get_rank_top_n(df: pd.DataFrame, change_col: str, industry_name: str, n: int) -> Tuple[list, list]:
            df[change_col] = pd.to_numeric(df[change_col], errors="coerce")
            df = df.dropna(subset=[change_col])

            # 涨幅前n
            top = df.nlargest(n, change_col)
            top_sectors = [{"name": row[industry_name], "change_pct": row[change_col]} for _, row in top.iterrows()]

            bottom = df.nsmallest(n, change_col)
            bottom_sectors = [
                {"name": row[industry_name], "change_pct": row[change_col]} for _, row in bottom.iterrows()
            ]
            return top_sectors, bottom_sectors

        # 优先东财接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_board_industry_name_em() 获取板块排行...")
            df = ak.stock_board_industry_name_em()
            if df is not None and not df.empty:
                change_col = "涨跌幅"
                name = "板块名称"
                return _get_rank_top_n(df, change_col, name, n)

        except Exception as e:
            logger.warning(f"[Akshare] 东财接口获取行业板块排行失败: {e}，尝试新浪接口")

        # 东财失败后，尝试新浪接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_sector_spot() 获取行业板块排行(新浪)...")
            df = ak.stock_sector_spot(indicator="行业")
            if df is None or df.empty:
                return None
            change_col = "涨跌幅"
            name = "板块"
            return _get_rank_top_n(df, change_col, name, n)

        except Exception as e:
            logger.exception(f"[Akshare] 新浪接口获取板块排行也失败: {e}")
            return None

    def get_indices(self, market: Market) -> list[MarketIndex]:
        rows = self._get_main_indices(market.value.lower()) or []
        result: list[MarketIndex] = []
        for row in rows:
            raw_code = str(row.get("code") or "")
            code = raw_code.removeprefix("sh").removeprefix("sz")
            symbol = canonical_symbol(code, market)
            result.append(
                MarketIndex(
                    symbol=symbol,
                    name=str(row.get("name") or symbol),
                    market=market,
                    provider=self.name,
                    price=float(row.get("current") or 0),
                    change=float(row.get("change") or 0),
                    change_pct=float(row.get("change_pct") or 0),
                    volume=int(row["volume"] * 100) if row.get("volume") is not None else None,
                    amount=float(row["amount"]) if row.get("amount") is not None else None,
                )
            )
        return result

    def get_market_stats(self, market: Market) -> MarketStats:
        if market is not Market.CN:
            raise ValueError("AKShare market breadth supports CN only")
        row = self._get_market_stats()
        if not row:
            raise RuntimeError("AKShare returned no market breadth")
        return MarketStats(
            market=market,
            provider=self.name,
            up_count=int(row.get("up_count") or 0),
            down_count=int(row.get("down_count") or 0),
            flat_count=int(row.get("flat_count") or 0),
            limit_up_count=int(row.get("limit_up_count") or 0),
            limit_down_count=int(row.get("limit_down_count") or 0),
            total_amount=(float(row["total_amount"]) * 1e8 if row.get("total_amount") is not None else None),
        )

    def get_sector_rankings(self, market: Market) -> SectorRankings:
        if market is not Market.CN:
            raise ValueError("AKShare sector rankings support CN only")
        rankings = self._get_sector_rankings() or ([], [])
        return SectorRankings(market=market, provider=self.name, top=rankings[0], bottom=rankings[1])

    def fetch_market_snapshot(self, market: Market) -> BatchQuoteResult:
        if market is not Market.CN:
            raise ValueError("AKShare full-market snapshot supports CN only")
        import akshare as ak

        frame = ak.stock_zh_a_spot_em()
        result = BatchQuoteResult()
        if frame is None or frame.empty:
            return result
        for row in frame.to_dict(orient="records"):
            try:
                symbol = canonical_symbol(str(row.get("代码") or ""), Market.CN)
                quote = quote_from_value(
                    {
                        "name": row.get("名称"),
                        "price": row.get("最新价"),
                        "change_pct": row.get("涨跌幅"),
                        "change_amount": row.get("涨跌额"),
                        "volume": (safe_int(row.get("成交量"), 0) or 0) * 100,
                        "amount": row.get("成交额"),
                        "open": row.get("今开"),
                        "high": row.get("最高"),
                        "low": row.get("最低"),
                        "pre_close": row.get("昨收"),
                    },
                    symbol=symbol,
                    provider=self.name,
                )
                if quote is not None:
                    result.data[symbol] = quote
                    result.providers_used[symbol] = self.name
            except (TypeError, ValueError):
                continue
        return result


__all__ = ["AkShareProvider", "is_hk_stock_code"]
