import { describe, expect, it } from 'vitest';
import { formatFixed, formatPercent, isFiniteNumber } from '../number';

describe('number formatting', () => {
  it('treats missing and non-finite values as unavailable', () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, '1.2']) {
      expect(isFiniteNumber(value)).toBe(false);
      expect(formatFixed(value)).toBe('—');
      expect(formatPercent(value, { fallback: 'unavailable' })).toBe('unavailable');
    }
  });

  it('formats fixed decimals with an optional sign on positives only', () => {
    expect(formatFixed(3.14159)).toBe('3.14');
    expect(formatFixed(3.14159, { digits: 1, signed: true })).toBe('+3.1');
    expect(formatFixed(0, { signed: true })).toBe('0.00');
    expect(formatFixed(-2, { digits: 0, signed: true })).toBe('-2');
  });

  it('formats ratios as percentages', () => {
    expect(formatPercent(0.1234)).toBe('12.3%');
    expect(formatPercent(0.1234, { digits: 2, signed: true })).toBe('+12.34%');
    expect(formatPercent(-0.05, { digits: 2, signed: true })).toBe('-5.00%');
    expect(formatPercent(0, { signed: true })).toBe('0.0%');
  });
});
