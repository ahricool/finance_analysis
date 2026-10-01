import { describe, expect, it } from 'vitest';
import { compareDailyPatternCandidates, dailyPatternMarketDate, detectDailyPatterns } from '../dailyPatterns';
import { candle, dated, falling, engulfing, hammer, mirror, star } from './fixtures/dailyPatterns';
const options = { marketDate: '2026-10-01' };
function fullRecoveryStar() {
  const bars = star();
  bars.at(-1)!.close = 100;
  bars.at(-1)!.high = 100.5;
  return bars;
}
function volumeHistory() {
  return dated([...Array.from({ length: 14 }, () => candle(110, 110)), ...engulfing()]);
}
const latest = (bars: ReturnType<typeof engulfing>) => detectDailyPatterns(bars, options).at(-1)!;


describe('daily candlestick rules', () => {
  it.each([
    ['bullish_engulfing', engulfing], ['bearish_engulfing', () => mirror(engulfing())],
    ['hammer', hammer], ['shooting_star', () => mirror(hammer())],
    ['morning_star', fullRecoveryStar], ['evening_star', () => mirror(fullRecoveryStar())],
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
  it('keeps the higher-quality engulfing over a lower-quality morning star on the same day', () => {
    const bars = star();
    const winner = latest(bars);
    const noEngulfing = bars.map(bar => ({ ...bar }));
    noEngulfing[7]!.open = 95.6;
    noEngulfing[7]!.close = 96; // Same middle body geometry, now bullish: only engulfing is invalidated.
    const runnerUp = latest(noEngulfing);
    expect(winner.type).toBe('bullish_engulfing');
    expect(runnerUp.type).toBe('morning_star');
    expect(winner.quality).toBeGreaterThan(runnerUp.quality);
    expect(detectDailyPatterns(bars, options).filter(event => event.date === winner.date)).toHaveLength(1);
  });
  it('uses star specificity only when rounded qualities match', () => {
    const bars = fullRecoveryStar();
    const winner = latest(bars);
    const noStar = bars.map(bar => ({ ...bar }));
    noStar[6]!.high = 110;
    const engulfingOnly = latest(noStar);
    expect(winner.type).toBe('morning_star');
    expect(engulfingOnly.type).toBe('bullish_engulfing');
    expect(winner.quality).toBe(engulfingOnly.quality);
  });
  it('sorts by quality, then specificity, then stable type for exact ties', () => {
    // Engulfing and hammer hard geometry gates are mutually exclusive;
    // test the shared comparator directly for this specificity tie.
    const candidates = [
      { type: 'hammer', quality: 73 }, { type: 'bullish_engulfing', quality: 73 },
      { type: 'morning_star', quality: 73 }, { type: 'bearish_engulfing', quality: 86 },
      { type: 'shooting_star', quality: 73 }, { type: 'evening_star', quality: 73 },
    ] as const;
    const expected = ['bearish_engulfing', 'evening_star', 'morning_star', 'bullish_engulfing', 'hammer', 'shooting_star'];
    expect([...candidates].sort(compareDailyPatternCandidates).map(event => event.type)).toEqual(expected);
    expect([...candidates].reverse().sort(compareDailyPatternCandidates).map(event => event.type)).toEqual(expected);
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
  it('ignores all Preview volume changes and never adds a volume reason', () => {
    const bars = volumeHistory();
    const previewOptions = { marketDate: bars.at(-1)!.tradeDate };
    const events = [50, 500, 5000].map(volume => {
      bars.at(-1)!.volume = volume;
      return detectDailyPatterns(bars, previewOptions).at(-1)!;
    });
    expect(events[0]).toBeDefined();
    for (const event of events) {
      expect(event.confirmed).toBe(false);
      expect(event).toEqual(events[0]);
      expect(event.reasons.some(reason => reason.includes('成交量'))).toBe(false);
    }
  });
  it('does not let Preview volume lift a below-threshold match into the displayed events', () => {
    const bars = dated([
      ...Array.from({ length: 13 }, () => candle(102, 102)),
      ...[101.5, 101.2, 100.9, 100.6, 100.3, 100].map(close => candle(close + 0.1, close)),
      candle(100, 99), candle(98.95, 100.35, 98.5, 100.5),
    ]);
    expect(detectDailyPatterns(bars, options)).toEqual([]);
    bars.at(-1)!.volume = 5000;
    expect(detectDailyPatterns(bars, { marketDate: bars.at(-1)!.tradeDate })).toEqual([]);
    expect(latest(bars).quality).toBeGreaterThanOrEqual(70);
    expect(latest(bars).confirmed).toBe(true);
  });
  it('gives confirmed completion-day volume at most five bonus points', () => {
    const bars = volumeHistory();
    const base = latest(bars);
    expect(base.confirmed).toBe(true);
    for (const volume of [150, 5000]) {
      bars.at(-1)!.volume = volume;
      const boosted = latest(bars);
      expect(boosted.quality - base.quality).toBe(5);
      expect(boosted.reasons.some(reason => reason.includes('成交量'))).toBe(true);
    }
    bars.forEach(bar => { bar.volume = NaN; });
    expect(latest(bars).quality).toBe(base.quality);
  });
  it('uses at most twenty prior bars, including an abnormal last six, without older or future volumes', () => {
    const bars = volumeHistory();
    const base = latest(bars);
    bars[0]!.volume = 100000; // Outside the twenty-bar reference.
    bars.slice(-7, -1).forEach(bar => { bar.volume = 200; });
    bars.at(-1)!.volume = 156; // (14 * 100 + 6 * 200) / 20 = 130; ratio 1.20 => +2.
    const event = latest(bars);
    expect(event.quality - base.quality).toBe(2);
    expect(event.reasons.at(-1)).toContain('20 个有效样本均量的 1.20 倍');
    const future = { ...candle(100, 101), tradeDate: '2026-09-23', volume: 1000000 };
    expect(detectDailyPatterns([...bars, future], options).find(item => item.date === event.date)).toEqual(event);
  });
  it('includes the first two star candles in volume reference, while trend still excludes them', () => {
    const bars = dated([...Array.from({ length: 12 }, () => candle(110, 110)), ...fullRecoveryStar()]);
    const base = latest(bars);
    expect(base.type).toBe('morning_star');
    bars.at(-3)!.volume = 500;
    bars.at(-2)!.volume = 500;
    bars.at(-1)!.volume = 168; // (18 * 100 + 2 * 500) / 20 = 140; ratio 1.20 => +2.
    const event = latest(bars);
    expect(event.type).toBe('morning_star');
    expect(event.quality - base.quality).toBe(2);
    expect(event.reasons[1]).toBe(base.reasons[1]);
    expect(event.reasons.at(-1)).toContain('20 个有效样本均量的 1.20 倍');
  });
  it('requires ten positive finite samples without requiring a full twenty-bar history', () => {
    const bars = dated([...Array.from({ length: 3 }, () => candle(110, 110)), ...engulfing()]);
    const base = latest(bars);
    bars.at(-1)!.volume = 5000;
    expect(latest(bars).quality - base.quality).toBe(5); // Exactly ten preceding samples.
    for (const invalid of [0, -10, NaN, Infinity]) {
      bars[0]!.volume = invalid;
      const event = latest(bars);
      expect(event.quality).toBe(base.quality);
      expect(event.reasons.some(reason => reason.includes('成交量'))).toBe(false);
    }
    const short = engulfing();
    const shortBase = latest(short);
    short.at(-1)!.volume = 5000;
    expect(latest(short)).toEqual(shortBase);
  });
  it('cannot create a shape or a trend with high volume alone', () => {
    const bars = volumeHistory();
    bars.at(-1)!.open = 98.1; // Does not fully engulf the preceding body.
    bars.at(-1)!.volume = 5000;
    expect(detectDailyPatterns(bars, options).some(event => event.date === bars.at(-1)!.tradeDate)).toBe(false);
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
