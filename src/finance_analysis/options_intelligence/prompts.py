"""Explain computed option evidence, never infer order flow or recompute scores."""

from finance_analysis.llm.prompting import FA_REFERENCE, bounded, reference_tables

COMMON = (
    """# 背景
你研究美股已计算的期权异常和风险，输入为低频快照，数据能力及覆盖有局限。

# 目标
{goal}

# 调研要求
1. 先核对日期、来源、历史样本和证据等级，再比较保护需求、异常活跃与流动性三个独立维度，不相加重算分数。
2. 不预测股价、不输出买卖建议。不得编造大单、机构仓位、主动买卖、净开仓或净空头；Put成交、OI和Skew不能证明方向。
3. Indicative不是NBBO；权利金估算不是真实成交额。未知报价/OI日期不推断实时性或次日确认；预热不足不当历史分位数。
4. 说明主要证据、替代解释和局限。此任务不做通用网页搜索；公开事件仅在输入或可核验FA资料提供截止时点前证据时确认，否则写可能或未知。
"""
    + FA_REFERENCE
)

SUMMARY = (
    COMMON.format(goal="汇总本次扫描的覆盖、主要异常证券及风险；区分保护需求与方向猜测，不将前15个样本代表全市场。")
    + """
# 交付
只输出中文JSON对象，无代码围栏或额外字段：market_overview(str), notable_symbols(list[str]),
protection_vs_direction(str), data_limits(list[str]), risk_notes(list[str])。
notable_symbols仅从top_candidates选择；数据不足时如实说明，不虚构扫描成功。
"""
)
EXPLANATION = (
    COMMON.format(goal="解释指定证券在选定快照时点的异常为何值得关注，列出可能催化、替代解释与交易风险。")
    + """
# 交付
只输出中文JSON对象，无代码围栏或额外字段：why_it_matters(str), possible_catalysts(list[str]),
protection_vs_direction(str), alternative_explanations(list[str]), data_limits(list[str]), trading_risks(list[str])。
区分观察事实与推断；FA补充核查在对应理由中注明数据日期和来源，不能改写已有评分。
"""
)
TABLES = """## 表格用途
- data：单证券日期/报价时点/评分与覆盖，或全市场扫描计数；failed/unfinished不是无异常。解释以computed_at为截止，日报以trade_date为截止。
- top_candidates：日报最多15个主要异常样本，比较三个独立评分与证据等级，不是交易推荐。
- scores及其子表：已有规则分数/方法/置信度/缺口，分值不是概率；不同方法的观察风险与历史分位不可混用。
- anomalous_contracts：最多12个异常合约的结论、报价与OI时效，通过symbol标识合约；events列表示触发类型，不代表独立资金来源。
- context/calendar：快照时点已知事件背景；recent_prices为前复权收盘价格，只帮助解释位置，不据此预测方向。
- limitations/events：数据能力限制及已触发事件，子表parent_ref关联父行；同一合约多事件不可重复计票。
IV/RV为年化小数；iv_percentile及volume_percentile为百分位（0–100）；skew是波动率差，不是收益预测。
"""


def render_input(payload, system):
    return bounded(reference_tables(payload, TABLES), system)


def explanation_payload(latest):
    keys = """symbol trade_date observed_at computed_at mode underlying_price scores evidence_grade confidence
    history_days volume_history_days status iv_30d iv_30d_method iv_source iv_percentile iv_sample_count rv_20d
    iv_rv_ratio skew_30d skew_source skew_change put_call_volume_ratio volume_source volume_feed limitations""".split()
    view = {k: latest[k] for k in keys if k in latest}
    fields = """symbol option_type expiration strike data_source feed_type quote_timestamp observed_at volume_date oi_date
    volume open_interest volume_percentile volume_oi iv iv_timestamp bid ask spread events
    quote_status observed_risk risk notes limitations baseline_days oi_change""".split()
    ranked = sorted(
        [r for r in latest["contracts"] if r["events"]], key=lambda r: r["volume_percentile"] or 0, reverse=True
    )[:12]
    view["anomalous_contracts"] = [{k: r[k] for k in fields if k in r} for r in ranked]
    view["scores"] = {
        k: {f: value for f, value in score.items() if f != "components"} if isinstance(score, dict) else score
        for k, score in latest.get("scores", {}).items()
    }
    return view
