import type { PatternDirection, PatternStage, RealtimeQuote, TrendDirection } from '@/api/realtimeMarket';
import { calculateIntradayDirection, INTRADAY_ENTRY_MAX_AGE_MINUTES, intradayDirectionSortValue } from '@/utils/intradayDirection';
import { describe, expect, it } from 'vitest';

const NOW = new Date('2026-07-22T15:00:00Z');

interface QuoteOptions {
  direction?: PatternDirection;
  stage?: PatternStage;
  ageMinutes?: number;
  trendState?: TrendDirection;
  streak?: number;
  invalidationPrice?: number | null;
  lastPrice?: number;
  tradingDate?: string;
}

function quote(options: QuoteOptions = {}): RealtimeQuote {
  const stage = options.stage ?? 'confirmed';
  const eventTime = new Date(NOW.getTime() - (options.ageMinutes ?? 5) * 60_000).toISOString();
  return {
    code: 'AAPL',
    marketType: 'US',
    symbol: 'AAPL.US',
    available: true,
    eventTime: NOW.toISOString(),
    receivedAt: NOW.toISOString(),
    lastPrice: options.lastPrice ?? 101,
    trend1m: {
      timeframe: '1m',
      targetPeriod: 20,
      effectivePeriod: 20,
      minimumPeriod: 5,
      state: options.trendState ?? 'above',
      streak: options.streak ?? 2,
      confirmed: true,
    },
    pattern1m: {
      timeframe: '1m',
      status: 'active',
      tradingDate: options.tradingDate ?? '2026-07-22',
      signal: {
        timeframe: '1m',
        patternType: 'vwap_reclaim_breakdown',
        patternName: 'VWAP收复',
        direction: options.direction ?? 'bullish_continuation',
        stage,
        qualityScore: 80,
        occurredAt: eventTime,
        confirmedAt: stage === 'confirmed' ? eventTime : null,
        tradingDate: options.tradingDate ?? '2026-07-22',
        tradeSession: 'Regular',
        barsAgo: 1,
        sessionMinutesAgo: 1,
        invalidationPrice: options.invalidationPrice === undefined ? 100 : options.invalidationPrice,
        reasons: ['结构成立'],
        confirmed: stage === 'confirmed',
      },
    },
  };
}

describe('calculateIntradayDirection', () => {
  it('shares the direction calculation with A shares and respects the lunch break', () => {
    const at = new Date('2026-07-22T02:00:00Z');
    const value = quote();
    value.marketType = 'CN';
    value.eventTime = value.receivedAt = at.toISOString();
    value.pattern1m!.signal!.confirmedAt = '2026-07-22T01:55:00Z';
    expect(calculateIntradayDirection(value, 'CN', at)?.status).toBe('多头确认');
    expect(calculateIntradayDirection(value, 'CN', new Date('2026-07-22T04:00:00Z'))?.status).toBe('休市等待');
  });

  it.each(['eventTime', 'receivedAt'] as const)('accepts ±30 seconds inclusively and distinguishes stale/future %s', field => {
    for (const offset of [-31_000, -30_000, -10_000, 0, 10_000, 30_000, 31_000]) {
      const value = { ...quote(), [field]: new Date(NOW.getTime() + offset).toISOString() };
      const status = calculateIntradayDirection(value, 'US', NOW);
      expect(status?.status, `${field}: ${offset}ms`).toBe(offset < -30_000 ? '行情延迟' : offset > 30_000 ? '行情超前' : '多头确认');
      if (Math.abs(offset) > 30_000) expect(intradayDirectionSortValue(status)).toBe(6);
    }
  });

  it('distinguishes missing, malformed and receipt-only timestamps from stale quotes', () => {
    for (const changes of [{ eventTime: undefined }, { receivedAt: undefined }, { eventTime: 'invalid' },
      { receivedAt: 'invalid' }, { timestampKind: 'received' }]) {
      expect(calculateIntradayDirection({ ...quote(), ...changes }, 'US', NOW)?.status).toBe('时间异常');
    }
    expect(calculateIntradayDirection(quote(), 'US', new Date('invalid'))).toBeNull();
  });

  it('uses calendar-provided early close and prioritizes close even without a pattern', () => {
    const value = quote();
    value.sessionClose = '2026-07-22T15:00:00Z';
    value.pattern1m = { timeframe: '1m', status: 'none' };
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('当日已收盘');
  });

  it('does not confirm a stale minute trend using a fresh quote', () => {
    const value = quote();
    value.trend1m!.barTime = new Date(NOW.getTime() - 181_000).toISOString();
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('趋势更新延迟');
    value.trend1m!.barTime = new Date(NOW.getTime() - 180_000).toISOString();
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('多头确认');
  });

  it('applies the same future tolerance to trend and signal times without expiring completed minute bars at 30 seconds', () => {
    const value = quote();
    value.trend1m!.barTime = new Date(NOW.getTime() - 60_000).toISOString();
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('多头确认');
    for (const offset of [30_000, 31_000]) {
      const timestamp = new Date(NOW.getTime() + offset).toISOString();
      value.trend1m!.barTime = timestamp;
      value.pattern1m!.signal!.confirmedAt = timestamp;
      expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe(offset === 30_000 ? '多头确认' : '时间异常');
      value.trend1m!.barTime = NOW.toISOString();
      expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe(offset === 30_000 ? '多头确认' : '时间异常');
    }
    value.trend1m!.barTime = 'invalid';
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('时间异常');
  });
  it.each([
    [{ direction: 'bullish_continuation', stage: 'warning', ageMinutes: 5 }, '多头观察'],
    [{ direction: 'bullish_breakout', stage: 'confirmed', ageMinutes: 5 }, '多头确认'],
    [{ direction: 'bullish_breakout', stage: 'confirmed', ageMinutes: 11 }, '多头延续'],
    [{ direction: 'bearish_continuation', stage: 'warning', ageMinutes: 5, trendState: 'below', lastPrice: 99 }, '空头观察'],
    [{ direction: 'bearish_breakout', stage: 'confirmed', ageMinutes: 5, trendState: 'below', lastPrice: 99 }, '空头确认'],
    [{ direction: 'bullish_to_bearish', stage: 'confirmed', ageMinutes: 11, trendState: 'below', lastPrice: 99 }, '空头延续'],
  ] as const)('maps a valid directional structure to %s', (options, expected) => {
    expect(calculateIntradayDirection(quote(options), 'US', NOW)?.status).toBe(expected);
  });

  it('uses the centralized entry-age threshold', () => {
    expect(INTRADAY_ENTRY_MAX_AGE_MINUTES).toBe(10);
    expect(calculateIntradayDirection(quote({ ageMinutes: 10 }), 'US', NOW)?.status).toBe('多头确认');
    expect(calculateIntradayDirection(quote({ ageMinutes: 11 }), 'US', NOW)?.status).toBe('多头延续');
  });

  it.each([
    [{ direction: 'bullish_breakout', invalidationPrice: 100, lastPrice: 99 }, 'call'],
    [{ direction: 'bearish_breakout', trendState: 'below', invalidationPrice: 100, lastPrice: 101 }, 'put'],
  ] as const)('prioritizes an invalidation breach for %s structures', (options, direction) => {
    const value = calculateIntradayDirection(quote(options), 'US', NOW);
    expect(value?.status).toBe('已经失效');
    expect(value?.direction).toBe(direction);
  });

  it('expires an old warning that never confirmed', () => {
    expect(calculateIntradayDirection(quote({ stage: 'warning', ageMinutes: 11 }), 'US', NOW)?.status).toBe('信号过期');
  });

  it('does not expire a confirmed old signal while its trend structure remains valid', () => {
    const value = calculateIntradayDirection(quote({ stage: 'confirmed', ageMinutes: 30 }), 'US', NOW);
    expect(value?.status).toBe('多头延续');
    expect(value?.reason).toContain('不宜直接追高');
  });

  it.each([
    [{ streak: 1 }, 'trend streak'],
    [{ trendState: 'below' }, 'trend conflict'],
    [{ direction: 'neutral_wait', stage: 'forming' }, 'neutral direction'],
    [{ direction: 'neutral_wait', stage: 'warning', ageMinutes: 30 }, 'old neutral direction'],
  ] as const)('waits in consolidation for %s', (options, caseName) => {
    expect(calculateIntradayDirection(quote(options), 'US', NOW)?.status, caseName).toBe('震荡等待');
  });

  it('marks a prior New York trading date as historical', () => {
    expect(calculateIntradayDirection(quote({ tradingDate: '2026-07-21' }), 'US', NOW)?.status)
      .toBe('上个交易日信号');
  });

  it('marks a current-date signal closed at 16:00 New York time', () => {
    const marketClose = new Date('2026-07-22T20:00:00Z');
    expect(calculateIntradayDirection(quote(), 'US', marketClose)?.status).toBe('当日已收盘');
  });

  it('returns null for non-US and unavailable quotes', () => {
    expect(calculateIntradayDirection(quote(), 'HK', NOW)).toBeNull();
    expect(calculateIntradayDirection({ ...quote(), available: false }, 'US', NOW)).toBeNull();
  });

  it('returns null rather than throwing when trend or pattern data is missing', () => {
    expect(calculateIntradayDirection({ ...quote(), trend1m: undefined }, 'US', NOW)).toBeNull();
    expect(calculateIntradayDirection({ ...quote(), pattern1m: undefined }, 'US', NOW)).toBeNull();
  });

  it('returns null for insufficient trend history or invalid required event time', () => {
    const insufficient = quote();
    insufficient.trend1m = { ...insufficient.trend1m!, effectivePeriod: 4, minimumPeriod: 5 };
    expect(calculateIntradayDirection(insufficient, 'US', NOW)).toBeNull();

    const invalidTime = quote();
    invalidTime.pattern1m!.signal!.confirmedAt = 'invalid';
    expect(calculateIntradayDirection(invalidTime, 'US', NOW)).toBeNull();
  });

  it('does not invalidate a structure merely because no invalidation price is available', () => {
    expect(calculateIntradayDirection(quote({ invalidationPrice: null }), 'US', NOW)?.status).toBe('多头确认');
  });

  it('uses the injected now value for deterministic age calculations', () => {
    const value = quote({ ageMinutes: 5 });
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('多头确认');
    const later = new Date(NOW.getTime() + 6 * 60_000);
    value.eventTime = value.receivedAt = later.toISOString();
    expect(calculateIntradayDirection(value, 'US', later)?.status).toBe('多头延续');
  });

  it('returns consolidation waiting when complete data has no active signal', () => {
    const value = quote();
    value.pattern1m = { timeframe: '1m', status: 'none' };
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('震荡等待');
  });
});
