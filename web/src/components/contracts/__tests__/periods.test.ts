import { expect, it } from 'vitest';
import { aggregateContracts } from '../periods';

it('aggregates UTC native candles and omits incomplete historical buckets', () => {
  const bars = Array.from({ length: 12 }, (_, i) => ({
    timestamp: i * 60000, open: 10 + i, close: 11 + i, high: 12 + i, low: 9 + i, turnover: 10, volume: 1,
  })).filter((_, i) => i !== 7);
  const result = aggregateContracts(bars, '5m', 11 * 60000 + 1000);
  expect(result.bars).toEqual([{ timestamp: 0, open: 10, high: 16, low: 9, close: 15, volume: 5, turnover: 50 }]);
  expect(result.current).toMatchObject({ timestamp: 600000, volume: 2 });
});
