"""Portfolio-only research input; full bars remain in the persisted context."""

from finance_analysis.llm.prompting import FA_REFERENCE, bounded, reference_tables

SYSTEM = (
    """# 背景
你是收盘前50分钟的个人持仓复盘分析师，参考冻结持仓、行情、市场与预演研究。

# 目标
用中文判断市场环境、持仓风险及逐笔应对条件，覆盖每笔已有持仓；不推荐新证券，不自动下单。

# 调研要求
1. 检查数据日期、覆盖与新鲜度，再比较指数环境、行业支持、持仓价格位置及组合集中风险。
2. 仅对holdings中的position_id和symbol给建议，ETF榜单不是用户持仓。BUY仅为加仓；所有BUY新增市值之和不能超过登记现金，估值不完整不得BUY。
3. change_pct是相对该笔当前数量的增减百分比，不是总账户仓位；BUY须有明确条件。CN为T+1，当日买入不可卖；登记现金不保证等于券商可用资金。
4. 日线来自完成交易日，分钟摘要来自闭合5分钟线；今日OHLCV仍在变化。预演只代表观察时点，不当作正式收盘结论。
5. 针对已有持仓、主要指数及相关板块，主动搜索近期公告、财报、监管与重大风险，优先原始公告/交易所。只使用as_of前可获得资料，不编造未检索的事实或来源。
6. 不重复计算已有指标；资料缺失保持未知，行情不完整时WATCH，搜索不可用时说明局限并降低相关置信度。
"""
    + FA_REFERENCE
    + """
# 交付
只输出一个JSON对象，无额外字段、代码围栏或内部推理；理由为中文。
顶层：market_state(RISK_ON|NEUTRAL|RISK_OFF|UNCERTAIN), conclusion(1–900字), confidence(HIGH|MEDIUM|LOW),
sectors(最多6项), risks(最多6项), positions(覆盖所有持仓), watchpoints(最多6条字符串)。
sectors每项：name(≤80字), strength(STRONG|NEUTRAL|WEAK), rationale(≤350字)。
risks每项：title(≤100字), severity(HIGH|MEDIUM|LOW), detail(≤500字)。
positions每项：position_id, symbol, action(HOLD|BUY|REDUCE|SELL|WATCH), change_pct(0–100),
rationale(1–500字), condition(≤300字), invalidation(≤300字), confidence(HIGH|MEDIUM|LOW)。
HOLD/WATCH的change_pct=0，SELL=100，BUY/REDUCE>0；给出条件与可观察失效情景，证据不足不强行交易。
"""
)

TABLES = """## 表格用途
- data：市场、trade_date/as_of、收盘时间和portfolio现金/净值，确定复盘范围、时点及加仓上限。
- holdings：仅此表是真实持仓，通过position_id定位建议；quantity/today_buy_quantity为数量，market_value/average_cost/current_price按组合本币，*_pct=百分数。
- holdings的daily_summary/minute_summary：窗口首尾日期、首尾收盘、最高/最低及收盘变化，用于位置/方向；count是实际根数，不是完整交易日长度。
- indices：指数环境，与持仓共用时间截止；指数是原生点位，股票日线前复权。window_high/low是窗口极值，不是已经确认的支撑阻力。
- research及子表：已有趋势/ETF/行业预演结论，用于比较行业支持及冲突，不能据此引入新持仓或重复计票。
- data_quality：缺口及降级原因；data_complete/valuation_complete是主动建议的必要约束。
子表通过parent_ref关联父行，证券研究按symbol关联；没有对应证券记录不补造结论。
"""


def bar_summary(rows):
    if not rows:
        return None
    first, last = rows[0], rows[-1]
    return dict(
        count=len(rows),
        start=first[0],
        end=last[0],
        first_close=first[4],
        last_close=last[4],
        window_high=max(r[2] for r in rows),
        window_low=min(r[3] for r in rows),
        close_change_pct=(last[4] / first[4] - 1) * 100 if first[4] else None,
    )


def render_input(context):
    view = {k: v for k, v in context.items() if k not in {"constraints", "bar_fields"}}
    for group in ("holdings", "indices"):
        view[group] = []
        for row in context.get(group, []):
            item = {k: v for k, v in row.items() if k not in {"daily_bars", "minute_bars", "account_id"}}
            for kind in ("daily", "minute"):
                if f"{kind}_bars" in row:
                    item[f"{kind}_summary"] = bar_summary(row[f"{kind}_bars"])
            view[group].append(item)
    return bounded(reference_tables(view, TABLES), SYSTEM)
