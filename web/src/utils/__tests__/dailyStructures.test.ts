import { describe, expect, it } from 'vitest';
import { detectDailyStructures, recentDailyStructures, structureStatusLabel } from '../dailyStructures';
import { box, doubleBottom, triangle } from './fixtures/dailyStructures';
import { candle, dated, mirror } from './fixtures/dailyPatterns';
const options = { marketDate: '2027-01-01' };

describe('causal daily structures', () => {
  it.each([
    ['box', box], ['double_bottom', doubleBottom], ['double_top', () => mirror(doubleBottom())],
    ['ascending_triangle', () => triangle()], ['descending_triangle', () => triangle('descending')],
    ['symmetric_triangle', () => triangle('symmetric')],
  ] as const)('recognizes %s with frozen boundary evidence', (type, fixture) => {
    const bars = fixture();
    const event = detectDailyStructures(bars, options).find(event => event.type === type && event.status === 'forming');
    expect(event).toBeDefined();
    expect(event!.quality).toBeGreaterThanOrEqual(70);
    expect(event!.lines).toHaveLength(2);
    expect(event!.date > event!.startDate).toBe(true);
  });
  it.each([true, false])('records box breakout, retest and failure in either direction (%s)', bullish => {
    const input = dated([...box(), candle(106, 108), candle(108, 109), candle(109, 108),
      candle(106, 107, 105.2, 108), candle(106, 103)]);
    const bars = bullish ? input : mirror(input);
    const events = detectDailyStructures(bars, options);
    const breakout = events.find(event => event.type === 'box' && event.status === 'confirmed')!;
    expect(breakout.direction).toBe(bullish ? 'bullish' : 'bearish');
    const retest = events.find(event => event.type === (bullish ? 'breakout_retest' : 'breakdown_retest'))!;
    expect(retest).toBeDefined();
    expect(retest.structureId).toBe(breakout.structureId);
    const failure = events.find(event => event.structureId === breakout.structureId && event.status === 'invalidated')!;
    expect(failure.date).toBe(bars.at(-1)!.tradeDate);
    expect(recentDailyStructures(events, breakout.date).some(event => event.id === breakout.id)).toBe(false);
  });
  it.each([true, false])('requires neckline breakout for double reversals (%s)', bullish => {
    const input = dated([...doubleBottom(), candle(105, 108)]);
    const events = detectDailyStructures(bullish ? input : mirror(input), options);
    const type = bullish ? 'double_bottom' : 'double_top';
    expect(events.find(event => event.type === type && event.status === 'confirmed')?.date).toBe(input.at(-1)!.tradeDate);
  });
  it('does not promote a current-day breakout to a closed confirmation', () => {
    const bars = dated([...box(), candle(106, 108)]);
    const event = detectDailyStructures(bars, { marketDate: bars.at(-1)!.tradeDate })
      .find(event => event.type === 'box' && event.status === 'confirmed');
    expect(event?.barConfirmed).toBe(false);
    expect(structureStatusLabel(event!)).toBe('突破待收盘');
    expect(structureStatusLabel({ ...event!, status: 'invalidated' })).toBe('失效待收盘');
    expect(structureStatusLabel({ ...event!, type: 'breakout_retest' })).toBe('回测待收盘');
    expect(detectDailyStructures(bars)).toEqual([]);
  });
  it('does not skip intervening extrema in a box to manufacture double reversals', () => {
    const events = detectDailyStructures(box(), options);
    expect(events.some(event => event.type === 'double_top' || event.type === 'double_bottom')).toBe(false);
  });
  it('invalidates an ascending triangle on a wrong-direction break and does not backdate it', () => {
    const bars = dated([...triangle(), candle(80, 78)]);
    const events = detectDailyStructures(bars, options);
    expect(events.some(event => event.type === 'ascending_triangle' && event.status === 'invalidated' && event.date === bars.at(-1)!.tradeDate)).toBe(true);
    expect(events.some(event => event.type === 'ascending_triangle' && event.status === 'confirmed')).toBe(false);
  });
  it.each([true, false])('allows symmetric triangles to confirm in either direction (%s)', bullish => {
    const bars = dated([...triangle('symmetric'), bullish ? candle(116, 118) : candle(84, 82)]);
    const event = detectDailyStructures(bars, options).find(event => event.type === 'symmetric_triangle' && event.status === 'confirmed');
    expect(event?.direction).toBe(bullish ? 'bullish' : 'bearish');
    expect(event?.date).toBe(bars.at(-1)!.tradeDate);
  });
  it('does not repaint previous events when future bars are appended, and does not mutate bars', () => {
    const bars = dated([...doubleBottom(), candle(105, 108)]);
    const before = structuredClone(bars);
    const original = detectDailyStructures(bars, options);
    const future = dated([...bars, ...Array.from({ length: 30 }, (_, i) => candle(100 + i, 101 + i))]);
    expect(detectDailyStructures(future, options).filter(event => event.date <= bars.at(-1)!.tradeDate)).toEqual(original);
    expect(bars).toEqual(before);
    const pivotDate = bars[40]!.tradeDate;
    expect(original.filter(event => event.type === 'double_bottom').every(event => event.date > pivotDate)).toBe(true);
  });
  it('rejects flat prices, malformed bars, duplicate dates and insufficient samples', () => {
    expect(detectDailyStructures(dated(Array.from({ length: 100 }, () => candle(100, 100))), options)).toEqual([]);
    expect(detectDailyStructures(box().slice(0, 19), options)).toEqual([]);
    for (const invalid of ['price', 'date']) {
      const bars = box().slice(0, 30);
      if (invalid === 'price') bars[15]!.low = NaN;
      else bars[15]!.tradeDate = bars[14]!.tradeDate;
      expect(detectDailyStructures(bars, options)).toEqual([]);
    }
    expect(detectDailyStructures(box(), { ...options, minQuality: 101 })).toEqual([]);
  });
  it('only evaluates retests in 3–15 sessions and only after a confirmed breakout', () => {
    const bars = dated([...box(), candle(106, 108), candle(106, 107, 105.2, 108), candle(107, 108)]);
    expect(detectDailyStructures(bars, options).some(event => event.type === 'breakout_retest')).toBe(false);
  });
});
