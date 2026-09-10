export function formatScore(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

export function formatPredictedReturn(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}%`;
}

export const regimeLabels: Record<string, string> = { risk_on: '适合承担风险', neutral: '中性', risk_off: '降低风险' };

export const MODEL_TARGET_COPY = {
  cross_section_lgbm: {
    shortName: '横截面模型',
    target: '预测未来 5 个交易日相对市场的超额收益',
    detail: 'T+1 开盘 → T+5 收盘，相对市场超额收益',
    primaryMetric: 'Daily Rank IC',
    secondaryMetric: 'Top10 超额',
  },
  time_series_lgbm: {
    shortName: '时间序列模型',
    target: '预测未来 5 个交易日绝对上涨概率',
    detail: 'T+1 开盘 → T+5 收盘，绝对收益 > 0 的分类概率',
    primaryMetric: 'ROC AUC',
    secondaryMetric: '方向命中率',
  },
} as const;

export type TrainableModelKey = keyof typeof MODEL_TARGET_COPY;

export function isTrainableModelKey(value: string): value is TrainableModelKey {
  return value === 'cross_section_lgbm' || value === 'time_series_lgbm';
}

export function primaryMetricValue(modelKey: string, metrics: Record<string, unknown>): number | null {
  const key = modelKey === 'time_series_lgbm' ? 'rocAuc' : 'dailyRankIcMean';
  const value = metrics[key] ?? metrics.rankIc;
  return typeof value === 'number' ? value : null;
}

export function secondaryMetricValue(modelKey: string, metrics: Record<string, unknown>): number | null {
  const key = modelKey === 'time_series_lgbm' ? 'directionalHitRate' : 'top10ExcessReturnPct';
  const value = metrics[key];
  return typeof value === 'number' ? value : null;
}

export function scalarMetrics(metrics: Record<string, unknown> | null | undefined): Array<[string, number | null]> {
  if (!metrics) return [];
  return Object.entries(metrics).flatMap(([key, value]) => {
    if (value == null || typeof value === 'number') return [[key, value as number | null]];
    return [];
  });
}
