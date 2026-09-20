import { describe, expect, it } from 'vitest';
import { bucketOperations } from '../tradeMarkers';

describe('stock/strategy BST bucketing', () => {
  it('marks only BUY as B, only SELL as S, and mixed as T', () => {
    const buckets = [{ start: Date.parse('2026-09-01T01:00:00Z'), end: Date.parse('2026-09-02T00:00:00Z') }];
    expect(bucketOperations([{ executedAt: Date.parse('2026-09-01T01:45:00Z'), side: 'BUY' }], buckets)[0]?.type).toBe('B');
    expect(bucketOperations([{ executedAt: Date.parse('2026-09-01T01:45:00Z'), side: 'SELL' }], buckets)[0]?.type).toBe('S');
    expect(bucketOperations([
      { executedAt: Date.parse('2026-09-01T01:45:00Z'), side: 'BUY' },
      { executedAt: Date.parse('2026-09-01T06:20:00Z'), side: 'SELL' },
    ], buckets)[0]?.type).toBe('T');
  });
});
