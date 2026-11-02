import { describe, expect, it } from 'vitest';
import type { DailyBar } from '@/api/marketData';
import { OPTION_STRATEGIES, strategyHint } from '../catalog';
import { observeTrend, scoreStrategies } from '../scoring';
const now = new Date('2026-11-02T08:00:00Z');
function bars(values: number[]): DailyBar[] {
  return values.map((close, i) => ({ tradeDate: `2026-10-${String(10 + i).padStart(2, '0')}`, open: close,
    high: close + .3, low: close - .3, close, volume: 1000, amount: null }));
}
const up = bars(Array.from({ length: 21 }, (_, i) => 100 + i));
const down = bars(Array.from({ length: 21 }, (_, i) => 120 - i));
const sideways = bars(Array.from({ length: 21 }, (_, i) => 100 + (i % 2 ? .1 : 0)));
const score = (rows: ReturnType<typeof scoreStrategies>, id: string) => rows.find(row => row.id === id)!.score!;
describe('deterministic option strategy fit', () => {
  it('covers standard families and provides detailed explanations with concrete risk boundaries', () => {
    expect(OPTION_STRATEGIES.length).toBeGreaterThanOrEqual(50);
    expect(new Set(OPTION_STRATEGIES.map(s => s.id)).size).toBe(OPTION_STRATEGIES.length);
    for (const entry of OPTION_STRATEGIES) {
      const hint = strategyHint(entry);
      for (const label of ['结构：', '适用情景：', '收益与损失：', '执行要点：']) expect(hint).toContain(label);
      expect(hint.length).toBeGreaterThan(160);
    }
    expect(OPTION_STRATEGIES.find(s => s.id === 'naked-call')!.risk).toBe('unlimited');
    expect(OPTION_STRATEGIES.find(s => s.id === 'covered-put')!.risk).toBe('unlimited');
    expect(OPTION_STRATEGIES.find(s => s.id === 'long-call-butterfly')!.profile).toBe('range');
    expect(OPTION_STRATEGIES.find(s => s.id === 'long-iron-butterfly')!.profile).toBe('move');
  });
  it('ranks directional structures according to actual trend instead of option names', () => {
    const bullish = scoreStrategies(observeTrend(up, 'US', 'swing', undefined, now));
    const bearish = scoreStrategies(observeTrend(down, 'CN', 'swing', undefined, now));
    expect(score(bullish, 'long-call')).toBeGreaterThan(score(bullish, 'long-put'));
    expect(score(bearish, 'long-put')).toBeGreaterThan(score(bearish, 'long-call'));
    expect(score(bullish, 'bull-call-spread')).toBeGreaterThan(score(bullish, 'bear-call-spread'));
    expect(score(bearish, 'protective-put')).toBeGreaterThan(score(bullish, 'protective-put'));
    for (const row of bullish.filter(row => row.score !== null)) {
      expect(row.score).toBeGreaterThanOrEqual(0); expect(row.score).toBeLessThanOrEqual(100);
      expect(row.reasons.length).toBeGreaterThanOrEqual(2);
    }
    const values = bullish.map(row => row.score).filter((v): v is number => v !== null);
    expect(values).toEqual([...values].sort((a, b) => b - a));
    expect(bullish.slice(-3).every(s => s.profile === 'arbitrage' && s.score === null)).toBe(true);
  });
  it('favors range structures in a flat environment without fabricating IV or pricing evidence', () => {
    const flat = observeTrend(sideways, 'US', 'swing', undefined, now);
    const rows = scoreStrategies(flat);
    expect(score(rows, 'short-iron-condor')).toBeGreaterThan(score(rows, 'long-call'));
    expect(score(rows, 'long-call-butterfly')).toBeGreaterThan(score(rows, 'long-iron-butterfly'));
    expect(rows.find(s => s.id === 'long-box')!.reasons.join('')).toContain('无法由K线趋势评分');
    const noVolume = sideways.map(row => ({ ...row, volume: undefined as unknown as number }));
    expect(observeTrend(noVolume, 'CN', 'swing', undefined, now).status).toBe('ready');
  });
  it('uses 5 or 10 session returns and never leaks dates after a selected historical cutoff', () => {
    const short = observeTrend(up, 'CN', 'short', undefined, now);
    const swing = observeTrend(up, 'CN', 'swing', undefined, now);
    expect(short.count).toBe(6); expect(swing.count).toBe(11);
    expect(short.returnPct).toBeCloseTo(120 / 115 - 1);
    const historical = observeTrend(up, 'CN', 'swing', '2026-10-25', now);
    const poisoned = [...up, { ...up.at(-1)!, tradeDate: '2026-10-31', close: 999, high: 1000 }];
    expect(observeTrend(poisoned, 'CN', 'swing', '2026-10-25', now)).toEqual(historical);
    expect(historical.asOf).toBe('2026-10-25');
  });
  it('does not hide invalid or zero-volume bars, insufficient samples or conflicting duplicates', () => {
    for (const values of [up.slice(-3), [...up.slice(0, -1), { ...up.at(-1)!, low: 999 }],
      [...up.slice(0, -1), { ...up.at(-1)!, volume: 0 }], [...up, { ...up.at(-1)!, close: 121 }]]) {
      const observation = observeTrend(values, 'CN', 'swing', undefined, now);
      expect(observation.status).toBe('unavailable');
      expect(scoreStrategies(observation).every(row => row.score === null)).toBe(true);
    }
    expect(observeTrend([...up, up.at(-1)!], 'CN', 'swing', undefined, now).status).toBe('ready');
    expect(observeTrend(up, 'UNKNOWN', 'swing', undefined, now).status).toBe('unavailable');
  });
  it('marks today as preview and evaluates both markets with identical Kline rules', () => {
    const today = [...up, { ...up.at(-1)!, tradeDate: '2026-11-02' }];
    expect(observeTrend(today, 'CN', 'swing', undefined, now).preview).toBe(true);
    expect(observeTrend(today, 'US', 'swing', undefined, now).preview).toBe(true);
    const sameCN = scoreStrategies(observeTrend(up, 'CN', 'swing', undefined, now));
    expect(scoreStrategies(observeTrend(up, 'US', 'swing', undefined, now))).toEqual(sameCN);
  });
  it('is invariant to a shared price scale and handles completely flat prices without NaN', () => {
    const scaled = up.map(b => ({ ...b, open: b.open / 10, high: b.high / 10, low: b.low / 10, close: b.close / 10 }));
    const original = scoreStrategies(observeTrend(up, 'CN', 'swing', undefined, now));
    const adjusted = scoreStrategies(observeTrend(scaled, 'CN', 'swing', undefined, now));
    expect(adjusted.map(s => [s.id, s.score])).toEqual(original.map(s => [s.id, s.score]));
    const flat = up.map(b => ({ ...b, open: 100, close: 100, high: 100, low: 100 }));
    const observed = observeTrend(flat, 'US', 'short', undefined, now);
    expect(observed.status).toBe('ready'); expect(observed.direction).toBe(0);
    for (const row of scoreStrategies(observed)) expect(row.score === null || Number.isFinite(row.score)).toBe(true);
  });
});
