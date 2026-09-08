import { describe, expect, it } from 'vitest';
import { formatEps } from '../timelineFormat';

describe('formatEps', () => {
  it.each([
    [1.32, 'USD', '$1.32'], [15.2, 'CNY', '¥15.20'], [3.5, 'HKD', 'HK$3.50'],
    [2.1, null, '2.10'], [2.1, undefined, '2.10'], [2.1, '', '2.10'],
    [2.1, 'unknown', '2.10'], [2.1, 'XYZ', '2.10'], [2.1, 'EUR', '2.10'],
    [15.2, ' cny ', '¥15.20'], [0, 'USD', '$0.00'], [-1.32, 'USD', '$-1.32'],
  ])('formats %s with currency %s as %s', (value, currency, expected) => {
    expect(formatEps(value, currency)).toBe(expected);
  });

  it.each([null, undefined, '', '1.32', NaN, Infinity])('omits invalid EPS %s', value => {
    expect(formatEps(value, 'USD')).toBe('');
  });
});
