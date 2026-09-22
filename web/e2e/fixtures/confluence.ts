const empty = (module: string, weight: number) => ({ source_module: module, weight, status: 'unavailable', score: null, trade_date: null, source_generated_at: null, evidence: {}, reasons: ['没有可靠映射，保持缺失'] });
const signals = {
  industry: { ...empty('industry_strength', 25), status: 'positive', score: 25, trade_date: '2026-09-21', source_generated_at: '2026-09-21T11:10:00Z', evidence: { industry_name: '半导体', industry_code: 'I1', strength_rank: 4, strength_score: 92, rank_change_3d: 8, members_observed_at: '2026-09-21T11:10:00Z' }, reasons: ['行业半导体排名第4', '3D 排名 12 → 4（仅解释，不重复加分）', 'positive：1 × 权重 25 = 25 分'] },
  trend: { ...empty('trend_following', 30), status: 'positive', score: 30, trade_date: '2026-09-22', source_generated_at: '2026-09-22T10:40:00Z', evidence: { state: 'TRENDING', trend_lifecycle: 'IGNITION', rank: 8, fragility_score: 12, trend_score: 88, trend_acceleration: 0.3, trend_quality: 95 }, reasons: ['Lifecycle = IGNITION；State = TRENDING', 'Fragility = 12（低脆弱性）', 'positive：1 × 权重 30 = 30 分'] },
  quant: { ...empty('quant', 20), status: 'neutral', score: 10, trade_date: '2026-09-22', source_generated_at: '2026-09-22T11:00:00Z', evidence: { universe_rank: 25, final_score: 0.7, signal: 'hold' }, reasons: ['Quant Rank = 25；Signal = hold', 'neutral：0.5 × 权重 20 = 10 分'] },
  etf: empty('etf_rotation', 15),
  dragon_tiger: { ...empty('dragon_tiger_flow', 10), status: 'positive', score: 10, trade_date: '2026-09-22', source_generated_at: '2026-09-22T11:30:00Z', evidence: { range_days: 1, net_inflow: 100000, institution_net_inflow: 10000, hot_money_net_inflow: null, records: [{ trade_date: '2026-09-22', range_days: 1, net_inflow: 100000, institution_net_inflow: 10000, hot_money_net_inflow: null }], concept_flows: [{ name: '半导体', net_inflow: 1000000 }] }, reasons: ['龙虎榜 1D 榜净流入 = 100000 CNY', 'positive：1 × 权重 10 = 10 分'] },
};
const row = { instrument_id: 1, code: '600001.SH', name: '测试股票', confluence_score: 88.24, available_weight: 85, available_signal_count: 4, positive_signal_count: 3, eligible: true, strong_confluence: true, signals, reasons: Object.values(signals).filter(s => s.status !== 'unavailable').flatMap(s => s.reasons), generated_at: '2026-09-22T12:30:00Z' };
export default {
  market: 'CN', trade_date: '2026-09-22', generated_at: row.generated_at, algorithm_version: 'confluence_v1',
  source_availability: Object.fromEntries(Object.entries(signals).map(([key, s]) => [key, { status: s.status === 'unavailable' ? 'unavailable' : 'available', count: s.status === 'unavailable' ? 0 : 1, trade_date: s.trade_date, reason: s.status === 'unavailable' ? s.reasons[0] : undefined }])),
  summary: { total: 1, eligible: 1, strong_confluence: 1, ignition_industry_strong: 1, top_industry_confluence: 1 },
  rules: { min_signals: 3, strong_min_signals: 4, strong_min_positive: 3, strong_min_score: 75 },
  total: 1, items: [row],
};
