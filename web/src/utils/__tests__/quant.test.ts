import { describe, expect, it } from 'vitest';
import { formatPercent, formatPredictedReturn, formatScore } from '../quant';

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
});
