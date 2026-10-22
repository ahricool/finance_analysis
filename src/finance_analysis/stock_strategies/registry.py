"""Frozen discovery identities; changing an economic rule requires a new version."""

from dataclasses import asdict, dataclass

INITIAL_CAPITAL = 1_000_000.0
VERSION = "1"


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    name: str
    markets: tuple[str, ...]
    family: str
    slots: int = 1
    atr: float = 0.0
    account_dd: float = 0.0
    cooldown: int = 0
    risk_engine: str = "20261021"
    breadth: bool = False
    breakout: bool = False
    version: str = VERSION

    def source_id(self, market):
        return SOURCE_IDS[(self.key, market)]

    def describe(self, market):
        regression = self.family == "regression" or (self.family == "breadth" and market == "US")
        hybrid = self.family == "hybrid" or (self.family == "breadth" and market == "CN")
        rules = [
            (
                "资金与成交",
                f"独立{INITIAL_CAPITAL:,.0f}本币模拟账户，最多{self.slots}仓。收盘决策、下一交易日开盘模拟成交；"
                "不计手续费/滑点、不借款，允许碎股；每笔预算=min(现金,开盘账户净值/仓数)，已有股数不每日再平衡。",
            ),
            (
                "数据与范围",
                "只读已同步前复权日线。美股股票使用us_trend（标普500/中盘400/纳指100并集），"
                "A股使用cn_trend（沪深300/中证500/1000/2000并集）；ETF使用当地指数ETF池。"
                "启动时冻结成分，后续保持范围以便连续比较。股票20日平均成交额门槛：美股500万美元/A股5000万元；成交额缺失使用价格×成交量代理。",
            ),
        ]
        if regression:
            rules += [
                (
                    "入场与排序",
                    "126日对数收盘OLS回归年化动量×R²降序，分数>0、收盘>MA100、"
                    "126日窗口内单日绝对涨跌幅<20%。每日有空位可补仓。",
                ),
                (
                    "退出与市场开关",
                    "每日收盘<MA100退出；月末最后交易日跌出合格排名前5退出，排名在市场门控前计算。"
                    "ETF非RISK_OFF才允许新增；ETF和60日Trend连续两日均RISK_OFF则清仓。",
                ),
            ]
        elif hybrid:
            rules += [
                (
                    "股票分支",
                    "Trend60≥60、RS60≥50，ETF及20日Trend市场均RISK_ON时入场，按Trend60降序。"
                    "跌破此前20日最低价，或20日市场分数<60，或ETF非RISK_ON时退出。",
                ),
                (
                    "ETF分支",
                    "ForceIndex2<0、当日下跌，EMA50上行且收盘在EMA50和MA200上方、126日收益>0，"
                    "Trend40≥60、RS40≥50（在冻结股票＋ETF横截面按研究公式计算）；基准亦在MA200上且126日收益>0。"
                    "按126日收益/max(20日年化波动,0.10)降序；股票优先，ETF使用剩余槽位。"
                    "ForceIndex转正、收盘<EMA50或基准过滤失效退出，两分支各用ATR3。",
                ),
            ]
        elif self.family == "momentum":
            rules += [
                ("入场与排序", "60日收益>0、收盘>MA200、126日收益>0，按60日收益降序。仅每月最后交易日允许新增。"),
                ("退出", "每日跌破MA50或ATR跟踪线退出；月末跌出合格排名前2也退出，其余日期不补仓。"),
            ]
        else:
            rules += [
                ("入场与排序", "收盘>MA20>MA50、收盘>MA200且126日收益>0，按MA20/MA50−1降序。"),
                ("退出", "收盘<MA20退出，无固定持有期限。"),
            ]
        if self.breakout:
            rules.append(("突破确认", "股票原始前40候选再筛收盘>昨日最高价，列表外不递补；ETF分支不变。"))
        if self.breadth:
            rules.append(
                (
                    "广度过滤与适配",
                    "合格股票站上各自MA50的比例≥40%才允许新增；连续两日<25%则全账户退出。"
                    "美股广度限定标普500成分股，A股使用已同步cn_trend股票池；"
                    "分母要求MA200可算及流动性合格。此为数据池适配，与历史研究收益分开。",
                )
            )
        if self.atr:
            rules.append(
                (
                    "ATR跟踪",
                    f"ATR14采用Wilder平滑，倍数{self.atr:g}。初始线=买入开盘−倍数×信号日ATR；"
                    "以后仅上调，以买入价/持仓最高收盘为峰值。收盘跌破此前跟踪线，次开盘退出，不作盘中止损。",
                )
            )
        else:
            rules.append(("ATR跟踪", "不设ATR止损（ATR0）。"))
        if self.account_dd:
            trigger = "达到" if self.risk_engine == "20261020" else "严格超过"
            reset = "首笔成功重新入场时" if self.risk_engine == "20261020" else "暂停结束且空仓时"
            rules.append(
                (
                    "账户回撤与恢复",
                    f"相对本轮峰值回撤{trigger}{self.account_dd:.0%}，下一开盘清仓；"
                    f"从清仓计划首个开盘起暂停{self.cooldown}个交易日开盘，未完成卖出持续等待，{reset}重置本轮峰值。"
                    "账户风控峰值与全历史最大回撤的峰值分别维护，阈值不保证最大回撤不超限。",
                )
            )
        rules += [
            ("版本与研究来源", self.source_id(market)),
            (
                "上线适配与限制",
                "从本模块统一启动日期空仓开始，历史日线仅作指标预热。"
                "复用对应日期正式Trend60/市场状态及ETF市场状态，ETF强度在本轮共享计算；缺依赖则等待。"
                "指标最多270交易日预热，EMA/ATR从窗口连续样本重设种子，边界可能与研究全历史递推略有差异。"
                "当前成分不代表历史成分，研究置信度及历史高收益不构成模拟收益。"
                "MA/动量族允许股票及ETF，沿用统一流动性过滤和原研究CTVA排除规则。A股股票采用开盘涨跌幅限制代理，ETF不猜测涨跌幅类别（非实盘可成交证明）；前复权尺度变化按持仓估值桥接换算。",
            ),
        ]
        return dict(asdict(self), source_id=self.source_id(market), rules=[dict(label=k, text=v) for k, v in rules])


STRATEGIES = (
    StrategyDefinition("ma_dd30", "均线20/50／1仓／DD30暂停7日／ATR0", ("US",), "ma", account_dd=0.30, cooldown=7),
    StrategyDefinition(
        "regression_dd20",
        "回归月度排名＋市场开关＋账户DD20／暂停20日",
        ("US",),
        "regression",
        slots=5,
        account_dd=0.20,
        cooldown=20,
        risk_engine="20261020",
    ),
    StrategyDefinition("ma_atr3", "均线排列20／1仓／ATR3", ("US",), "ma", atr=3),
    StrategyDefinition("momentum60", "动量60／1仓／ATR3", ("US",), "momentum", atr=3),
    StrategyDefinition("ma_dd25", "单仓MA20/50＋账户DD25／冷静5日", ("US",), "ma", account_dd=0.25, cooldown=5),
    StrategyDefinition(
        "hybrid_score60", "股票＋ETF／市场分数60退出", ("CN",), "hybrid", slots=5, atr=3, risk_engine="20261020"
    ),
    StrategyDefinition(
        "hybrid_breakout",
        "股票ETF共用资金／股票收盘突破昨高",
        ("CN",),
        "hybrid",
        slots=5,
        atr=3,
        risk_engine="20261020",
        breakout=True,
    ),
    StrategyDefinition(
        "breadth", "股票ETF/回归系统＋广度过滤", ("CN", "US"), "breadth", slots=5, risk_engine="20261020", breadth=True
    ),
)
SOURCE_IDS = {
    ("ma_dd30", "US"): "US_local_f20_s50_long_n1_a0_dd0.3_c7",
    ("regression_dd20", "US"): "US_overlay_p60_ETFnotOFF_both_OFF_c2_a0.0_accountDD0.2_cool20",
    ("ma_atr3", "US"): "US_MARibbon_20_long_native_none_n1_a3",
    ("momentum60", "US"): "US_rot_Momentum_60_long_n1_b2_monthly_a3",
    ("ma_dd25", "US"): "US_risk_p0_dd0.25_cool5",
    ("hybrid_score60", "CN"): "CN_hyst_score60_ETFnotON_c1_DonchianLow20_a3.0_n5_ETF1",
    ("hybrid_breakout", "CN"): "cn_main_entry_stock_breakout",
    ("breadth", "CN"): "CN_hyst_score60_ETFnotON_c1_DonchianLow20_a3.0_n5_ETF1_BR_breadth50_e0.4_x0.25_c2_dd0.0",
    ("breadth", "US"): "US_overlay_p60_ETFnotOFF_both_OFF_c2_a0.0_BR_breadth50_e0.4_x0.25_c2_dd0.2",
}


def definition(key, market):
    return next((s for s in STRATEGIES if s.key == key and market in s.markets), None)


def parameters(spec, market):
    """The breadth family inherits different native parents in each market."""
    from dataclasses import replace

    if spec.family == "breadth":
        return replace(
            spec,
            family="hybrid" if market == "CN" else "regression",
            atr=3 if market == "CN" else 0,
            account_dd=0 if market == "CN" else 0.20,
            cooldown=0 if market == "CN" else 20,
        )
    return spec
