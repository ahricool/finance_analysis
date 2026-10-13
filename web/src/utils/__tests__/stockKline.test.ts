import { describe, expect, it } from 'vitest';
import { aggregateStockBars, stockPeriodKey } from '../stockKline';
import type { DailyBar } from '@/api/marketData';

const row = (tradeDate: string, values: Partial<DailyBar> = {}): DailyBar => ({
  tradeDate, open: 10, high: 12, low: 9, close: 11, volume: 100, amount: 1000, ...values,
});
describe('stock K-line aggregation', () => {
  it('uses Monday weeks across year boundaries and calendar months', () => {
    expect(stockPeriodKey('2026-01-01', '1w')).toBe('2025-12-29');
    expect(stockPeriodKey('2026-01-04', '1w')).toBe('2025-12-29');
    expect(stockPeriodKey('2026-01-05', '1w')).toBe('2026-01-05');
    expect(stockPeriodKey('2026-01-01', '1M')).toBe('2026-01');
  });
  it('aggregates sorted OHLCV, preserves unknown amount and does not mutate daily bars', () => {
    const rows = [row('2026-10-09', { high: 15, close: 14, amount: null }),
      row('2026-10-05'), row('2026-10-07', { low: 8 }), row('2026-10-12')];
    expect(aggregateStockBars(rows, '1w')).toEqual([
      row('2026-10-05', { high: 15, low: 8, close: 14, volume: 300, amount: null }),
      row('2026-10-12'),
    ]);
    expect(rows[1]).toEqual(row('2026-10-05'));
  });
  it('keeps month boundaries, partial periods and missing months without fabricated bars', () => {
    expect(aggregateStockBars([row('2026-01-30'), row('2026-03-02'), row('2026-03-03')], '1M'))
      .toEqual([row('2026-01-30'), row('2026-03-02', { volume: 200, amount: 2000 })]);
    expect(aggregateStockBars([], '1w')).toEqual([]);
  });
});
