import { describe, expect, it, vi } from 'vitest';
import type { IntradayBar } from '@/api/intradayMarket';
import { referenceSeries, structureOverlays } from '../overlays';
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


it('draws fixed box bounds and only confirmed supplied pivots', () => {
  const value = structureOverlays({ kind: 'breakout_up', phase: 'confirmed', background: 'bullish',
    since: '2026-11-12T16:00:00Z', asOf: '2026-11-12T16:00:00Z', oversold: false, reference: false,
    availableBars: 60, missingBars: 0, reasons: [],
    box: { upper: 101, lower: 99, startAt: '2026-11-12T15:20:00Z', endAt: '2026-11-12T15:50:00Z', atr: .5 },
    pivots: [{ kind: 'high', at: '2026-11-12T15:40:00Z', confirmedAt: '2026-11-12T15:43:00Z', price: 101 }],
  });
  expect(value).toHaveLength(4);
  expect(value.find(v => v.id === 'structure-event')?.points?.[0]?.timestamp).toBe(Date.parse('2026-11-12T15:59:00Z'));
  expect(value.find(v => v.id === 'structure-box-upper')?.points?.map(p => p.value)).toEqual([101, 101]);
  expect(structureOverlays(null)).toEqual([]);
});

it('marks the retest candle rather than the original breakout confirmation', () => {
  const structure = { kind: 'breakout_up' as const, phase: 'retest' as const, background: 'bullish' as const,
    confirmedAt: '2026-11-12T15:12:00Z', since: '2026-11-12T15:14:00Z', asOf: '2026-11-12T15:14:00Z',
    oversold: false, reference: false, availableBars: 44, missingBars: 0, reasons: [], pivots: [],
    box: { upper: 101.05, lower: 98.95, startAt: '2026-11-12T14:40:00Z', endAt: '2026-11-12T15:09:00Z', atr: .6 },
  };
  for (const asOf of ['2026-11-12T15:14:00Z', '2026-11-12T15:15:00Z']) {
    const marker = structureOverlays({ ...structure, asOf }).find(v => v.id === 'structure-event');
    expect(marker?.points?.[0]?.timestamp).toBe(Date.parse('2026-11-12T15:13:00Z'));
    expect(marker?.points?.[0]?.value).toBe(101.05);
  }
});
