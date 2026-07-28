import type { PatternDirection, PatternStage, RealtimeQuote, TrendDirection } from '@/api/realtimeMarket';
import { calculateZeroDteStatus, ZERO_DTE_ENTRY_MAX_AGE_MINUTES } from '@/utils/zeroDteStatus';
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

describe('calculateZeroDteStatus', () => {
  it.each([
    [{ direction: 'bullish_continuation', stage: 'warning', ageMinutes: 5 }, 'CALL观察'],
    [{ direction: 'bullish_breakout', stage: 'confirmed', ageMinutes: 5 }, 'CALL确认'],
    [{ direction: 'bullish_breakout', stage: 'confirmed', ageMinutes: 11 }, 'CALL延续'],
    [{ direction: 'bearish_continuation', stage: 'warning', ageMinutes: 5, trendState: 'below', lastPrice: 99 }, 'PUT观察'],
    [{ direction: 'bearish_breakout', stage: 'confirmed', ageMinutes: 5, trendState: 'below', lastPrice: 99 }, 'PUT确认'],
    [{ direction: 'bullish_to_bearish', stage: 'confirmed', ageMinutes: 11, trendState: 'below', lastPrice: 99 }, 'PUT延续'],
  ] as const)('maps a valid directional structure to %s', (options, expected) => {
    expect(calculateZeroDteStatus(quote(options), 'US', NOW)?.status).toBe(expected);
  });

  it('uses the centralized entry-age threshold', () => {
    expect(ZERO_DTE_ENTRY_MAX_AGE_MINUTES).toBe(10);
    expect(calculateZeroDteStatus(quote({ ageMinutes: 10 }), 'US', NOW)?.status).toBe('CALL确认');
    expect(calculateZeroDteStatus(quote({ ageMinutes: 11 }), 'US', NOW)?.status).toBe('CALL延续');
  });

  it.each([
    [{ direction: 'bullish_breakout', invalidationPrice: 100, lastPrice: 99 }, 'call'],
    [{ direction: 'bearish_breakout', trendState: 'below', invalidationPrice: 100, lastPrice: 101 }, 'put'],
  ] as const)('prioritizes an invalidation breach for %s structures', (options, direction) => {
    const value = calculateZeroDteStatus(quote(options), 'US', NOW);
    expect(value?.status).toBe('已经失效');
    expect(value?.direction).toBe(direction);
  });

  it('expires an old warning that never confirmed', () => {
    expect(calculateZeroDteStatus(quote({ stage: 'warning', ageMinutes: 11 }), 'US', NOW)?.status).toBe('信号过期');
  });

  it('does not expire a confirmed old signal while its trend structure remains valid', () => {
    const value = calculateZeroDteStatus(quote({ stage: 'confirmed', ageMinutes: 30 }), 'US', NOW);
    expect(value?.status).toBe('CALL延续');
    expect(value?.reason).toContain('不宜直接追高');
  });

  it.each([
    [{ streak: 1 }, 'trend streak'],
    [{ trendState: 'below' }, 'trend conflict'],
    [{ direction: 'neutral_wait', stage: 'forming' }, 'neutral direction'],
    [{ direction: 'neutral_wait', stage: 'warning', ageMinutes: 30 }, 'old neutral direction'],
  ] as const)('waits in consolidation for %s', (options, caseName) => {
    expect(calculateZeroDteStatus(quote(options), 'US', NOW)?.status, caseName).toBe('震荡等待');
  });

  it('marks a prior New York trading date as historical', () => {
    expect(calculateZeroDteStatus(quote({ tradingDate: '2026-07-21' }), 'US', NOW)?.status)
      .toBe('上个交易日信号');
  });

  it('marks a current-date signal closed at 16:00 New York time', () => {
    const marketClose = new Date('2026-07-22T20:00:00Z');
    expect(calculateZeroDteStatus(quote(), 'US', marketClose)?.status).toBe('当日已收盘');
  });

  it('returns null for non-US and unavailable quotes', () => {
    expect(calculateZeroDteStatus(quote(), 'HK', NOW)).toBeNull();
    expect(calculateZeroDteStatus({ ...quote(), available: false }, 'US', NOW)).toBeNull();
  });

  it('returns null rather than throwing when trend or pattern data is missing', () => {
    expect(calculateZeroDteStatus({ ...quote(), trend_1m: undefined }, 'US', NOW)).toBeNull();
    expect(calculateZeroDteStatus({ ...quote(), pattern_1m: undefined }, 'US', NOW)).toBeNull();
  });

  it('returns null for insufficient trend history or invalid required event time', () => {
    const insufficient = quote();
    insufficient.trend_1m = { ...insufficient.trend_1m!, effective_period: 4, minimum_period: 5 };
    expect(calculateZeroDteStatus(insufficient, 'US', NOW)).toBeNull();

    const invalidTime = quote();
    invalidTime.pattern_1m!.signal!.confirmed_at = 'invalid';
    expect(calculateZeroDteStatus(invalidTime, 'US', NOW)).toBeNull();
  });

  it('does not invalidate a structure merely because no invalidation price is available', () => {
    expect(calculateZeroDteStatus(quote({ invalidationPrice: null }), 'US', NOW)?.status).toBe('CALL确认');
  });

  it('uses the injected now value for deterministic age calculations', () => {
    const value = quote({ ageMinutes: 5 });
    expect(calculateZeroDteStatus(value, 'US', NOW)?.status).toBe('CALL确认');
    expect(calculateZeroDteStatus(value, 'US', new Date(NOW.getTime() + 6 * 60_000))?.status).toBe('CALL延续');
  });

  it('returns consolidation waiting when complete data has no active signal', () => {
    const value = quote();
    value.pattern_1m = { timeframe: '1m', status: 'none' };
    expect(calculateZeroDteStatus(value, 'US', NOW)?.status).toBe('震荡等待');
  });
});
