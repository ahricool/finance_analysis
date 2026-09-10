import { describe, expect, it } from 'vitest';
import {
  MODEL_TARGET_COPY,
  formatPercent,
  formatPredictedReturn,
  formatScore,
  primaryMetricValue,
  scalarMetrics,
} from '../quant';

describe('quant formatters', () => {
  it('does not render missing values as zero', () => {
    expect(formatScore(null)).toBe('—');
    expect(formatPercent(undefined)).toBe('—');
    expect(formatPredictedReturn(null)).toBe('—');
  });

  it('keeps predicted return in percentage-point units', () => {
    expect(formatPredictedReturn(1.4)).toBe('1.40%');
    expect(formatPercent(0.08)).toBe('8.0%');
  });

  it('describes distinct CS and TS targets and headline metrics', () => {
    expect(MODEL_TARGET_COPY.cross_section_lgbm.target).toContain('超额收益');
    expect(MODEL_TARGET_COPY.time_series_lgbm.target).toContain('上涨方向分数');
    expect(primaryMetricValue('cross_section_lgbm', { dailyRankIcMean: 0.08, rankIc: 0.01 })).toBe(0.08);
    expect(primaryMetricValue('time_series_lgbm', { rocAuc: 0.7 })).toBe(0.7);
    expect(scalarMetrics({ rocAuc: 0.7, assumptions: { cost: 10 } })).toEqual([['rocAuc', 0.7]]);
  });
});
