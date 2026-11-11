import { describe, expect, it, vi } from 'vitest';
import type { IntradayBar } from '@/api/intradayMarket';
import { referenceSeries } from '../overlays';
vi.mock('klinecharts', () => ({ registerOverlay: vi.fn() }));
const bars: IntradayBar[] = [
  { timestamp: 0, open: 10, high: 12, low: 8, close: 10, volume: 100, turnover: 1000, confirmed: true, partial: false, sampled: false, sampleCount: 0 },
  { timestamp: 60_000, open: 10, high: 22, low: 18, close: 20, volume: 200, turnover: 4000, confirmed: true, partial: false, sampled: false, sampleCount: 0 },
];
describe('reference line semantics', () => {
  it('distinguishes exact volume weighting, approximation and equal-weight minute means', () => {
    expect(referenceSeries(bars, 'vwap').points.at(-1)?.value).toBeCloseTo(5000 / 300);
    expect(referenceSeries(bars, 'mean').points.at(-1)?.value).toBe(15);
    expect(referenceSeries(bars.map(b => ({ ...b, turnover: null })), 'vwap').label).toContain('近似');
  });
  it('does not fabricate volume or bridge a missing minute', () => {
    expect(referenceSeries(bars.map(b => ({ ...b, volume: 0, turnover: null })), 'vwap').points).toEqual([]);
    expect(referenceSeries([bars[0]!, { ...bars[1]!, timestamp: 120_000 }], 'mean').points).toEqual([]);
  });
});
