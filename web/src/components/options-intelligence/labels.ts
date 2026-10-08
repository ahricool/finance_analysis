export const eventLabels: Record<string, string> = {
  PUT_VOLUME_SPIKE: 'Put 成交异常', CALL_VOLUME_SPIKE: 'Call 成交异常', VOLUME_OI_ANOMALY: '成交量/OI 异常',
  LARGE_PREMIUM_ACTIVITY: '大额权利金估算', BEARISH_SKEW_SPIKE: '下行偏斜升高', IV_SPIKE: '隐含波动率异常',
  IV_TERM_INVERSION: '波动率期限倒挂', LIQUIDITY_DRY_UP: '流动性不足', WIDE_BID_ASK_SPREAD: '买卖点差过宽',
  OI_BUILDUP_CONFIRMED: '次日 OI 增加确认',
};
export const reasonLabels: Record<string, string> = {
  valid_30d_atm_iv_unavailable: '没有有效30D ATM IV（零报价/占位IV/期限或字段不足）',
  underlying_quote_time_mismatch: '标的价格与期权报价时间不同步，未用于点差校准',
  quote_timestamp_unknown: '报价时间未知', stale_quote: '报价已过期', invalid_quote: '无效或缺失报价',
  indicative_not_nbbo: 'Indicative 报价，非 NBBO', zero_bid: '零 Bid', very_low_premium: '极低权利金',
  near_expiry: '临近到期', deep_otm: '深度价外', fresh_real_quotes_unavailable: '没有新鲜真实报价',
  insufficient_history_and_absolute_activity_evidence: '历史不足，且无满足门槛的成交活跃证据',
  insufficient_protection_demand_evidence: '保护需求证据不足', valid_delta_bracket_unavailable: '有效 Delta 数据不足',
  oi_as_of_unknown: 'OI 数据日期未知，无法次日确认', volume_session_inferred: '成交量交易日结合最后成交日期推定',
  volume_session_unknown_or_stale: '成交量日期未知或属于其他交易日，未参与当日评分',
  multiplier_unverified_premium_unavailable: '合约乘数未确认，无法计算权利金',
  iv_timestamp_unknown: 'IV 时间未知，仅作低频链参考', indicative_modified_quotes_delayed_trades: 'Indicative 报价经过修改，成交延迟',
  greeks_unavailable: '当前数据源不提供 Greeks，25Δ Skew 无法计算', iv_unavailable: '当前数据源不提供 IV',
  daily_volume_unavailable: '数据源不提供日累计成交量', underlying_price_missing: '标的现价缺失',
};
export const formatOptionNumber = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value) ? 'N/A' : value.toLocaleString(undefined, { maximumFractionDigits: digits });
export const formatOptionPct = (value: number | null | undefined) => value == null ? 'N/A' : `${(value * 100).toFixed(2)}%`;
export const reasonLabel = (value: string) => reasonLabels[value] ?? value;
