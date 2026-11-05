"""Explain computed option evidence, never infer order flow or recompute scores."""

from copy import deepcopy
import json

from finance_analysis.llm.prompting import FA_REFERENCE, reference_tables

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
- events：按严重程度排列的已触发事件，保留value/reference、来源及时点；证券级事件contract_symbol为空。期限倒挂reference保留前后期限和IV，历史缺期限时只列匹配项，不推断唯一对应。
- anomalous_contracts：仅异常相关合约，event_ids关联events，按关联事件严重程度排列，不按成交量裁剪；不同来源/时间/报价的冲突保留。unlinked_event_types表示原快照缺少触发明细。
- context/calendar：快照时点已知事件背景；recent_prices为前复权收盘价格，只帮助解释位置，不据此预测方向。
- sources/limitation_definitions：共享来源与限制定义；source_id及limitations_ids/notes_ids引用相应ID。只有完全相同事实去重，不把同一合约多事件当独立资金。
IV/RV为年化小数；iv_percentile及volume_percentile为百分位（0–100）；skew是波动率差，不是收益预测。
"""


def render_input(payload):
    return reference_tables(payload, TABLES)


def explanation_payload(latest):
    keys = """symbol trade_date observed_at computed_at mode underlying_price scores evidence_grade confidence
    history_days volume_history_days status iv_30d iv_30d_method iv_source iv_percentile iv_sample_count rv_20d
    iv_rv_ratio skew_30d skew_source skew_change put_call_volume_ratio volume_source volume_feed limitations""".split()
    view = {k: latest[k] for k in keys if k in latest}

    def unique(rows):
        seen, result = set(), []
        for row in rows:
            identity = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
            if identity not in seen:
                seen.add(identity)
                result.append(row)
        return result

    event_fields = "contract_symbol event_type severity value reference source feed_type data_time volume_date oi_date direction explanation evidence_grade confidence".split()
    events = unique([{k: deepcopy(row[k]) for k in event_fields if k in row} for row in latest.get("events", [])])
    events.sort(key=lambda row: -(row.get("severity") or 0))
    for i, event in enumerate(events):
        event["event_id"] = f"e{i + 1}"
        if event.get("event_type") == "IV_TERM_INVERSION":
            reference = event.get("reference") or {}
            for side in ("front", "back"):
                term = reference.get(side)
                if isinstance(term, dict):
                    reference[side] = {
                        k: term[k] for k in ("expiration", "dte", "atm_iv", "source", "feed_type") if k in term
                    }
                else:
                    # Older snapshots may give only an IV number. Preserve it and expose
                    # matching same-feed terms without inventing which expiry was used.
                    reference[side] = term
                    matches = [
                        t
                        for t in latest.get("term_structure", [])
                        if t.get("source") == event.get("source")
                        and t.get("feed_type") == event.get("feed_type")
                        and t.get("atm_iv") == term
                        and term is not None
                    ]
                    reference[f"{side}_terms"] = [
                        {k: t[k] for k in ("expiration", "dte", "atm_iv") if k in t} for t in matches
                    ]
            event["reference"] = reference
    view["events"] = events

    fields = """symbol option_type expiration strike data_source feed_type quote_timestamp observed_at volume_date oi_date
    volume open_interest volume_percentile volume_oi iv iv_timestamp bid ask spread
    quote_status observed_risk risk notes limitations baseline_days oi_change""".split()
    # Keep all event-bearing contracts, rather than a volume-only top-N that can
    # suppress liquidity/OI risks. This still excludes the ordinary raw option chain.
    contracts = []
    for row in latest.get("contracts", []):
        related = [
            e
            for e in events
            if e.get("contract_symbol") == row["symbol"]
            and e.get("source") == row.get("data_source")
            and e.get("feed_type") == row.get("feed_type")
        ]
        if not related and not row.get("events"):
            continue
        item = {k: deepcopy(row[k]) for k in fields if k in row}
        for event in related:
            duplicate = {
                "PUT_VOLUME_SPIKE": "volume",
                "CALL_VOLUME_SPIKE": "volume",
                "VOLUME_OI_ANOMALY": "volume_oi",
                "WIDE_BID_ASK_SPREAD": "spread",
            }.get(event["event_type"])
            observation_time = row.get(
                "quote_timestamp" if event["event_type"] == "WIDE_BID_ASK_SPREAD" else "observed_at"
            )
            if (
                duplicate
                and observation_time
                and observation_time == event.get("data_time")
                and item.get(duplicate) == event.get("value")
            ):
                item.pop(duplicate, None)
            if event["event_type"] == "OI_BUILDUP_CONFIRMED" and item.get("oi_change") == event.get("reference"):
                item.pop("oi_change", None)
        item["event_ids"] = [e["event_id"] for e in related]
        unlinked = [kind for kind in row.get("events", []) if kind not in {e["event_type"] for e in related}]
        if unlinked:
            item["unlinked_event_types"] = unlinked
        contracts.append(item)
    view["anomalous_contracts"] = unique(contracts)
    priorities = {e["event_id"]: e.get("severity") or 0 for e in events}
    view["anomalous_contracts"].sort(key=lambda r: -max((priorities[e] for e in r["event_ids"]), default=0))
    view["scores"] = {
        k: {f: deepcopy(value) for f, value in score.items() if f != "components"} if isinstance(score, dict) else score
        for k, score in latest.get("scores", {}).items()
    }
    # Repeated source labels and caveats get one shared definition. Only exact
    # equality is interned; conflicting feeds/times/observations remain separate.
    sources, texts = {}, {}

    def source_id(source, feed):
        key = (source, feed)
        if key not in sources:
            sources[key] = f"s{len(sources) + 1}"
        return sources[key]

    def intern(row):
        if not isinstance(row, dict):
            return
        source_key = "data_source" if "data_source" in row else "source"
        if source_key in row and "feed_type" in row:
            row["source_id"] = source_id(row.pop(source_key), row.pop("feed_type"))
        for key in ("limitations", "notes"):
            if isinstance(row.get(key), list):
                values = row.pop(key)
                ids = []
                for value in values:
                    if value not in texts:
                        texts[value] = f"l{len(texts) + 1}"
                    ids.append(texts[value])
                row[key + "_ids"] = list(dict.fromkeys(ids))
        for value in row.values():
            if isinstance(value, dict):
                intern(value)
            elif isinstance(value, list):
                for child in value:
                    intern(child)

    view = deepcopy(view)
    intern(view)
    view["sources"] = [
        dict(source_id=identity, source=source, feed_type=feed) for (source, feed), identity in sources.items()
    ]
    view["limitation_definitions"] = [dict(limitation_id=identity, text=text) for text, identity in texts.items()]
    return view
