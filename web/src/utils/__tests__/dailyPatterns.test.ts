import { describe, expect, it } from 'vitest';
import { dailyPatternMarketDate, detectDailyPatterns } from '../dailyPatterns';
import { candle, dated, falling, engulfing, hammer, mirror, star } from './fixtures/dailyPatterns';
const options = { marketDate: '2026-10-01' };

describe('daily candlestick rules', () => {
  it.each([
    ['bullish_engulfing', engulfing], ['bearish_engulfing', () => mirror(engulfing())],
    ['hammer', hammer], ['shooting_star', () => mirror(hammer())],
    ['morning_star', star], ['evening_star', () => mirror(star())],
  ] as const)('detects %s with explicit evidence', (type, fixture) => {
    const bars = fixture();
    const events = detectDailyPatterns(bars, options);
    const event = events.find(item => item.date === bars.at(-1)!.tradeDate)!;
    expect(event.type).toBe(type);
    expect(event.quality).toBeGreaterThanOrEqual(70);
    expect(event.quality).toBeLessThanOrEqual(100);
    expect(event.confirmed).toBe(true);
    expect(event.reasons).toHaveLength(3);
    expect(event.timestamp).toBe(Date.parse(`${event.date}T00:00:00Z`));
  });
  it.each([engulfing, hammer, star])('rejects the same geometry without the required trend', fixture => {
    const bars = fixture();
    const flat = dated([...Array.from({ length: 6 }, () => candle(100, 100)), ...bars.slice(6)]);
    const opposite = dated([...mirror(falling()), ...bars.slice(6)]);
    for (const sample of [flat, opposite, mirror(flat), mirror(opposite)]) {
      const events = detectDailyPatterns(sample, options);
      if (fixture === star) expect(events.some(event => event.type === 'morning_star' || event.type === 'evening_star')).toBe(false);
      else expect(events).toEqual([]);
    }
  });
  it('requires full engulfment and excludes tiny preceding bodies', () => {
    for (const last of [candle(98.1, 101), candle(97.8, 99.9)]) {
      const bars = engulfing(); bars[7] = { ...last, tradeDate: bars[7]!.tradeDate };
      expect(detectDailyPatterns(bars, options)).toEqual([]);
      expect(detectDailyPatterns(mirror(bars), options)).toEqual([]);
    }
    const bars = engulfing(); bars[6]!.open = 98.01;
    expect(detectDailyPatterns(bars, options)).toEqual([]);
  });
  it('excludes doji, excessive opposite shadows and weak star penetration symmetrically', () => {
    for (const last of [candle(98.99, 99, 94.5, 99.2), candle(98, 99, 94.5, 100)]) {
      const bars = dated([...falling(), last]);
      expect(detectDailyPatterns(bars, options)).toEqual([]);
      expect(detectDailyPatterns(mirror(bars), options)).toEqual([]);
    }
    const bars = star(); bars[8]!.close = 97.9;
    // May qualify as an engulfing, but never as a star with <60% penetration.
    expect(detectDailyPatterns(bars, options).some(event => event.type === 'morning_star')).toBe(false);
    expect(detectDailyPatterns(mirror(bars), options).some(event => event.type === 'evening_star')).toBe(false);
  });
  it('filters weak geometry even when trend and hard gates pass', () => {
    const bars = dated([101.5, 101.2, 100.9, 100.6, 100.3, 100].map(close => candle(close + 0.1, close))
      .concat([candle(100, 99), candle(98.95, 100.1, 98.5, 100.5)]));
    expect(detectDailyPatterns(bars, options)).toEqual([]);
    expect(detectDailyPatterns(bars, { ...options, minQuality: 0 })).toEqual([]);
    expect(detectDailyPatterns(engulfing(), { ...options, minQuality: 101 })).toEqual([]);
  });
  it('keeps one event per date and prioritizes the star over a higher-quality engulfing', () => {
    const bars = star();
    const winner = detectDailyPatterns(bars, options).at(-1)!;
    const noStar = bars.map(bar => ({ ...bar }));
    noStar[6]!.high = 110; // Invalidates only the first star candle's body/range.
    const runnerUp = detectDailyPatterns(noStar, options).at(-1)!;
    expect(winner.type).toBe('morning_star');
    expect(runnerUp.type).toBe('bullish_engulfing');
    expect(runnerUp.quality).toBeGreaterThan(winner.quality);
    expect(detectDailyPatterns(bars, options).filter(event => event.date === winner.date)).toHaveLength(1);
  });
  it('never uses future bars or mutates input', () => {
    const bars = engulfing();
    const before = structuredClone(bars);
    const expected = detectDailyPatterns(bars, options);
    for (const future of [candle(1, 2), candle(999, 400)]) {
      const extended = [...bars, { ...future, tradeDate: '2026-09-09' }];
      expect(detectDailyPatterns(extended, options).filter(event => event.date <= '2026-09-08')).toEqual(expected);
    }
    expect(bars).toEqual(before);
  });
  it('treats optional volume as a maximum five-point bonus', () => {
    const bars = engulfing();
    const base = detectDailyPatterns(bars, options)[0]!;
    bars.at(-1)!.volume = 150;
    expect(detectDailyPatterns(bars, options)[0]!.quality - base.quality).toBe(5);
    bars.forEach(bar => { bar.volume = NaN; });
    expect(detectDailyPatterns(bars, options)[0]!.quality).toBe(base.quality);
  });
  it('rejects malformed bars, duplicate dates and insufficient history without bridging holes', () => {
    for (const value of [NaN, Infinity, 0, -1, 200]) {
      const bars = engulfing(); bars[4]!.low = value;
      expect(detectDailyPatterns(bars, options)).toEqual([]);
    }
    const bars = engulfing(); bars[4]!.tradeDate = bars[3]!.tradeDate;
    expect(detectDailyPatterns(bars, options)).toEqual([]);
    expect(detectDailyPatterns(engulfing().slice(1), options)).toEqual([]);
  });
  it('keeps today and unknown completion status Preview; historical bars are confirmed', () => {
    expect(detectDailyPatterns(engulfing(), { marketDate: '2026-09-08' })[0]!.confirmed).toBe(false);
    expect(detectDailyPatterns(engulfing())[0]!.confirmed).toBe(false);
    expect(detectDailyPatterns(engulfing(), { marketDate: '2026-09-09' })[0]!.confirmed).toBe(true);
  });
  it('uses exchange-local calendar dates across DST and UTC midnight', () => {
    expect(dailyPatternMarketDate('US', new Date('2026-09-09T02:00:00Z'))).toBe('2026-09-08');
    expect(dailyPatternMarketDate('US', new Date('2026-01-09T04:30:00Z'))).toBe('2026-01-08');
    expect(dailyPatternMarketDate('CN', new Date('2026-09-08T17:00:00Z'))).toBe('2026-09-09');
    expect(dailyPatternMarketDate('HK', new Date('2026-09-08T17:00:00Z'))).toBe('2026-09-09');
    expect(dailyPatternMarketDate('unknown', new Date())).toBeUndefined();
  });
});
