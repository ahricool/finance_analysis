import legacy from './confluence';
const empty = (source: string, weight: number) => ({ source_module: source, weight, score: null, strength: null, normalized_weight: null, contribution: null, status: 'unavailable', trade_date: null, source_generated_at: null, evidence: {}, reasons: ['该股票无核心指标，不参与分母'] });
const signals = {
  macro: { ...empty('macro', 15), score: 12, strength: 80, normalized_weight: 15.79, contribution: 12.63, status: 'positive', trade_date: '2026-09-21', evidence: { regime: 'RISK_ON', risk_score: 80, signal_coverage: .9 }, reasons: ['使用宏观看板原生核心风险偏好分'] },
  etf: { ...empty('etf_rotation', 20), score: 18, strength: 90, normalized_weight: 21.05, contribution: 18.95, status: 'positive', trade_date: '2026-09-22', evidence: { etfs: [{ code: '512480.SH', name: '半导体ETF', composite_score: 90, mapping_reasons: ['半导体产业链代理'] }] }, reasons: ['关联ETF去重等权，缺失不参与'] },
  industry: { ...legacy.items[0]!.signals.industry, weight: 15, score: 13.8, strength: 92, normalized_weight: 15.79, contribution: 14.53 },
  trend: { ...legacy.items[0]!.signals.trend, score: 26.4, strength: 88, normalized_weight: 31.58, contribution: 27.79, evidence: { ...legacy.items[0]!.signals.trend.evidence, matrix: [
    { period: 20, routes: { trend: 88, breakout: 80, rebound: 0 }, dominant: 'trend' },
    { period: 40, routes: { trend: 90, breakout: null, rebound: 0 }, dominant: 'trend' },
    { period: 60, routes: { trend: 86, breakout: 0, rebound: 0 }, dominant: 'trend' },
  ] } },
  quant: { ...legacy.items[0]!.signals.quant, weight: 7, strength: 50, score: 3.5, normalized_weight: 7.37, contribution: 3.68 },
  options: empty('options_intelligence', 5),
  sentiment: { ...empty('market_sentiment', 4), strength: 75, score: 3, normalized_weight: 4.21, contribution: 3.16, status: 'positive', trade_date: '2026-09-22', evidence: { heat_score: 75, state: 'ACTIVE', limit_up_count: 63 } },
  dragon_tiger: { ...legacy.items[0]!.signals.dragon_tiger, weight: 4, strength: 100, score: 4, normalized_weight: 4.21, contribution: 4.21 },
};
export default { ...legacy, algorithm_version: 'confluence_v2',
  rules: { min_signals: 2, strong_min_signals: 2, strong_min_positive: 2, strong_min_score: 75, max_signals: 10, weights: { macro: 15, etf: 20, industry: 15, trend: 30, quant: 7, options: 5, sentiment: 4, dragon_tiger: 4 } },
  source_availability: Object.fromEntries(Object.entries(signals).map(([key,s]) => [key, { status: s.status === 'unavailable' ? 'unavailable' : 'available', count: s.status === 'unavailable' ? 0 : 1, trade_date: s.trade_date, evidence: s.evidence }])),
  summary: { ...legacy.summary, candidate_count: 14 },
  items: [{ ...legacy.items[0]!, signals, available_weight: 95, available_signal_count: 7, positive_signal_count: 6, confluence_score: 84.95 }],
};
