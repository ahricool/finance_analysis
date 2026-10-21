import type { PatternDirection, PatternStage, RealtimeQuote, TrendDirection } from '@/api/realtimeMarket';
import { calculateIntradayDirection, INTRADAY_ENTRY_MAX_AGE_MINUTES } from '@/utils/intradayDirection';
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
    market_type: 'US',
    symbol: 'AAPL.US',
    available: true,
    event_time: NOW.toISOString(),
    received_at: NOW.toISOString(),
    last_price: options.lastPrice ?? 101,
    trend_1m: {
      timeframe: '1m',
      target_period: 20,
      effective_period: 20,
      minimum_period: 5,
      state: options.trendState ?? 'above',
      streak: options.streak ?? 2,
      confirmed: true,
    },
    pattern_1m: {
      timeframe: '1m',
      status: 'active',
      trading_date: options.tradingDate ?? '2026-07-22',
      signal: {
        timeframe: '1m',
        pattern_type: 'vwap_reclaim_breakdown',
        pattern_name: 'VWAP收复',
        direction: options.direction ?? 'bullish_continuation',
        stage,
        quality_score: 80,
        occurred_at: eventTime,
        confirmed_at: stage === 'confirmed' ? eventTime : null,
        trading_date: options.tradingDate ?? '2026-07-22',
        trade_session: 'Regular',
        bars_ago: 1,
        session_minutes_ago: 1,
        invalidation_price: options.invalidationPrice === undefined ? 100 : options.invalidationPrice,
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
    value.market_type = 'CN';
    value.event_time = value.received_at = at.toISOString();
    value.pattern_1m!.signal!.confirmed_at = '2026-07-22T01:55:00Z';
    expect(calculateIntradayDirection(value, 'CN', at)?.status).toBe('多头确认');
    expect(calculateIntradayDirection(value, 'CN', new Date('2026-07-22T04:00:00Z'))?.status).toBe('休市等待');
  });

  it('rejects stale, missing, future and receipt-only quote timestamps', () => {
    const old = new Date(NOW.getTime() - 91_000).toISOString();
    for (const changes of [{ event_time: old }, { received_at: old }, { event_time: undefined },
      { event_time: new Date(NOW.getTime() + 6_000).toISOString() }, { timestamp_kind: 'received' }]) {
      expect(calculateIntradayDirection({ ...quote(), ...changes }, 'US', NOW)?.status).toBe('行情延迟');
    }
    expect(calculateIntradayDirection(quote(), 'US', new Date('invalid'))).toBeNull();
  });

  it('uses calendar-provided early close and prioritizes close even without a pattern', () => {
    const value = quote();
    value.session_close = '2026-07-22T15:00:00Z';
    value.pattern_1m = { timeframe: '1m', status: 'none' };
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('当日已收盘');
  });

  it('does not confirm a stale minute trend using a fresh quote', () => {
    const value = quote();
    value.trend_1m!.bar_time = new Date(NOW.getTime() - 181_000).toISOString();
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('行情延迟');
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
    expect(calculateIntradayDirection({ ...quote(), trend_1m: undefined }, 'US', NOW)).toBeNull();
    expect(calculateIntradayDirection({ ...quote(), pattern_1m: undefined }, 'US', NOW)).toBeNull();
  });

  it('returns null for insufficient trend history or invalid required event time', () => {
    const insufficient = quote();
    insufficient.trend_1m = { ...insufficient.trend_1m!, effective_period: 4, minimum_period: 5 };
    expect(calculateIntradayDirection(insufficient, 'US', NOW)).toBeNull();

    const invalidTime = quote();
    invalidTime.pattern_1m!.signal!.confirmed_at = 'invalid';
    expect(calculateIntradayDirection(invalidTime, 'US', NOW)).toBeNull();
  });

  it('does not invalidate a structure merely because no invalidation price is available', () => {
    expect(calculateIntradayDirection(quote({ invalidationPrice: null }), 'US', NOW)?.status).toBe('多头确认');
  });

  it('uses the injected now value for deterministic age calculations', () => {
    const value = quote({ ageMinutes: 5 });
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('多头确认');
    const later = new Date(NOW.getTime() + 6 * 60_000);
    value.event_time = value.received_at = later.toISOString();
    expect(calculateIntradayDirection(value, 'US', later)?.status).toBe('多头延续');
  });

  it('returns consolidation waiting when complete data has no active signal', () => {
    const value = quote();
    value.pattern_1m = { timeframe: '1m', status: 'none' };
    expect(calculateIntradayDirection(value, 'US', NOW)?.status).toBe('震荡等待');
  });
});
