"""Versioned, conservative industry sensitivities to observed cross-asset proxies.

Coefficients are research assumptions, not fitted betas or return probabilities.
CN uses global style only: US Treasury/credit must not masquerade as CN policy.
"""

from dataclasses import dataclass
from math import isfinite

from finance_analysis.stocks.industry_etf import CN_INDUSTRY_ETF, US_INDUSTRY_ETF, MAPPING_VERSION

VERSION = "sector_macro_v1"
MIN_COVERAGE = 0.65
FACTOR_LABELS = {"risk": "全球风险偏好", "credit": "美国信用偏好", "rates": "美债价格趋势"}


@dataclass(frozen=True)
class Profile:
    name: str
    coefficients: dict[str, float]
    reason: str


PROFILES = {
    # A股仅使用全球风格代理，系数限幅；不将美国利率、信用解释为国内宽松或经济增长。
    "cn_growth": Profile("A股成长风格", {"risk": 0.8}, "全球风险偏好对成长风格的弱代理，不代表国内流动性"),
    "cn_cyclical": Profile("A股周期风格", {"risk": 0.6}, "仅观察全球顺周期偏好，不推断国内需求或商品利润"),
    "cn_defensive": Profile("A股防御风格", {"risk": -0.4}, "风险偏弱时相对防御适配；不代表行业绝对上涨"),
    # 美股成长同时受风险、信用和贴现环境影响；TLT上涨只是美债价格代理，不宣称已经降息。
    "us_growth": Profile(
        "美股成长风格", {"risk": 0.5, "credit": 0.2, "rates": 0.3}, "风险及信用改善、美债走强支持成长风格"
    ),
    "us_cyclical": Profile("美股周期风格", {"risk": 0.6, "credit": 0.3}, "风险及信用偏好改善支持周期风格，不预测盈利"),
    "us_defensive": Profile(
        "美股防御风格", {"risk": -0.35, "rates": 0.15}, "风险偏弱体现相对防御，美债走强提供有限支持"
    ),
    # 银行不使用风险偏好反向分；没有收益率曲线和银行资产质量模型，不从TLT单独推断净息差。
    "us_credit": Profile(
        "美股金融信用敏感", {"risk": 0.2, "credit": 0.6}, "金融依赖信用环境；缺少曲线信息，不判断利率对净息差的影响"
    ),
    "us_rates": Profile(
        "美股利率敏感",
        {"risk": 0.15, "credit": 0.25, "rates": 0.6},
        "地产及公用事业使用美债和信用代理，不代表政策利率预测",
    ),
}

# 这里只为已审核的行业代理建立宏观风格；未列入者不从ETF名字猜测。
CN_PROXY_PROFILES = {
    "512480.SH": "cn_growth",  # 半导体及电子：成长风格。
    "159732.SZ": "cn_growth",  # 消费电子：成长风格，不套必需消费防御规则。
    "516510.SH": "cn_growth",  # 云计算及IT设备：成长风格。
    "159852.SZ": "cn_growth",  # 软件：成长风格。
    "159326.SZ": "cn_growth",  # 数字经济及计算机：成长风格。
    "512170.SH": "cn_defensive",  # 医疗服务、器械及中药：有限的相对防御风格。
    "159996.SZ": "cn_cyclical",  # 家电：可选消费，非防御消费。
    "159565.SZ": "cn_cyclical",  # 汽车零部件：顺周期风格。
    "515970.SH": "cn_cyclical",  # 新材料与制造需求：只观察顺周期风格。
    "516970.SH": "cn_cyclical",  # 基建机械：不将海外信号解释为国内刺激政策。
    "562500.SH": "cn_cyclical",  # 机器人及自动化：制造资本开支风格。
}
CN_EXACT_PROFILES = {
    "881134.TI": "cn_defensive",  # 食品加工制造：日常消费相对防御。
    "884120.TI": "cn_defensive",  # 软饮料：日常消费，不扩展到白酒。
    "884123.TI": "cn_defensive",  # 肉制品：日常消费相对防御。
    "884124.TI": "cn_defensive",  # 调味发酵品：日常消费相对防御。
    "884125.TI": "cn_defensive",  # 乳品：日常消费相对防御。
    "884126.TI": "cn_defensive",  # 其他食品：有限日常消费风格。
    "884297.TI": "cn_defensive",  # 预加工食品：有限日常消费风格。
}
US_SECTOR_PROFILES = {
    "Technology": "us_growth",  # 科技：风险、信用及美债贴现代理。
    "Consumer Cyclical": "us_cyclical",  # 可选消费：顺周期。
    "Industrials": "us_cyclical",  # 工业：顺周期，不直接推断订单。
    "Consumer Defensive": "us_defensive",  # 必需消费：相对防御，农业另行排除。
    "Healthcare": "us_defensive",  # 医疗：相对防御，生物科技另行覆盖。
    "Financial Services": "us_credit",  # 金融：信用敏感，不使用宏观差即利好银行规则。
    "Real Estate": "us_rates",  # 地产：利率和融资敏感。
    "Utilities": "us_rates",  # 公用事业：融资与美债贴现代理。
}
US_EXACT_PROFILES = {
    ("Healthcare", "Biotechnology"): "us_growth",  # 生物科技研发融资敏感，不套成熟医疗防御规则。
    ("Communication Services", "Telecom Services"): "us_defensive",  # 电信运营：相对防御。
    ("Communication Services", "Internet Content & Information"): "us_growth",  # 互联网内容：成长风格。
}


def profile_for(market, industry):
    """Exact source classifications only; ETF proxy is a grouping aid, never a price input."""
    key = industry.get("industry_code", "")
    if market == "CN":
        proxy = CN_INDUSTRY_ETF.get(key)
        return CN_EXACT_PROFILES.get(key) or CN_PROXY_PROFILES.get(proxy.etf_code if proxy else None)
    pair = (industry.get("sector"), key)
    if market == "US" and pair in US_INDUSTRY_ETF:
        if pair[1] in {"Farm Products", "Agricultural Inputs"}:
            return None  # 农业缺少产品/成本/政策信息，不能由风险偏好机械反转。
        return US_EXACT_PROFILES.get(pair) or US_SECTOR_PROFILES.get(pair[0])
    return None


def valid(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and 0 <= value <= 100


def adapt(background, classification, market):
    """Frozen evidence with per-factor signed contributions; missing is never a neutral guess."""
    background = background or {}
    evidence = dict(
        background,
        adaptation_score=None,
        macro_method=VERSION,
        mapping_version=MAPPING_VERSION,
        market=market,
        profiles=[],
        exclusions=[],
    )
    industries = (classification or {}).get("industries", [])
    evidence["classification"] = classification or {}
    if not industries:
        evidence["adaptation_reason"] = "无目标日期可用行业分类，宏观适配留空"
        return evidence
    states = background.get("states") or {}
    factors = {
        "risk": background.get("risk_score"),
        "credit": {"HEALTHY": 100, "WEAK": 0, "NEUTRAL": 50}.get(states.get("credit")),
        "rates": {"EASING": 100, "PRESSURE": 0, "NEUTRAL": 50}.get(states.get("rates")),
    }
    groups = {}
    for industry in industries:
        key = profile_for(market, industry)
        if not key:
            proxy = CN_INDUSTRY_ETF.get(industry.get("industry_code")) if market == "CN" else None
            if proxy and proxy.etf_code == "512800.SH":
                reason = "A股银行缺国内收益率曲线、信用及息差信息，不按全球风险偏好反转"
            elif (proxy and proxy.etf_code == "159825.SZ") or industry.get("industry_code") in {
                "Farm Products",
                "Agricultural Inputs",
            }:
                reason = "农业缺产品价格、成本和政策信息，不按风险偏好反转"
            else:
                reason = "未审核敏感性或缺少行业专属宏观数据，不使用统一或反向分"
            evidence["exclusions"].append(dict(industry=industry, reason=reason))
        else:
            groups.setdefault(key, []).append(industry)
    scores = []
    for key, members in sorted(groups.items()):
        profile = PROFILES[key]
        available = {k: v for k, v in profile.coefficients.items() if valid(factors.get(k))}
        total = sum(abs(v) for v in profile.coefficients.values())
        coverage = sum(abs(v) for v in available.values()) / total
        covered = coverage >= MIN_COVERAGE
        terms = [
            dict(
                key=k,
                label=FACTOR_LABELS[k],
                value=factors[k],
                coefficient=v,
                contribution=v * (factors[k] - 50) / coverage if covered else None,
            )
            for k, v in profile.coefficients.items()
            if k in available
        ]
        score = round(50 + sum(t["contribution"] for t in terms), 4) if covered else None
        evidence["profiles"].append(
            dict(
                key=key,
                name=profile.name,
                reason=profile.reason,
                industries=members,
                coverage=coverage,
                strength=score,
                terms=terms,
                missing_factors=[FACTOR_LABELS[k] for k in profile.coefficients if k not in available],
            )
        )
        if score is not None:
            scores.append(score)
    # Do not cherry-pick supported memberships: unsupported industries/profiles leave the entire dimension empty.
    if not evidence["exclusions"] and len(scores) == len(groups) and scores:
        evidence["adaptation_score"] = round(sum(scores) / len(scores), 4)
        evidence["adaptation_reason"] = "不同风格档案去重后等权；50为中性，相对适配不代表绝对收益"
    else:
        evidence["adaptation_reason"] = "存在未审核行业或有效宏观因子覆盖不足65%，宏观适配留空并分摊权重"
        if evidence["exclusions"]:
            evidence["adaptation_reason"] += "；" + "；".join(sorted({row["reason"] for row in evidence["exclusions"]}))
    return evidence
