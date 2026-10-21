import type { RealtimePatternSignal, RealtimeQuote } from '@/api/realtimeMarket';
import type { MarketType } from '@/api/watchList';

export const INTRADAY_ENTRY_MAX_AGE_MINUTES = 10;
export const US_MARKET_TIMEZONE = 'America/New_York';

export type IntradayDirectionStatus =
  | '休市等待'
  | '行情延迟'
  | '多头观察'
  | '多头确认'
  | '多头延续'
  | '空头观察'
  | '空头确认'
  | '空头延续'
  | '信号过期'
  | '已经失效'
  | '震荡等待'
  | '当日已收盘'
  | '上个交易日信号';

export interface IntradayDirectionResult {
  status: IntradayDirectionStatus;
  direction: 'call' | 'put' | 'neutral';
  entryState: 'watch' | 'fresh' | 'extended' | 'expired' | 'invalid' | 'closed' | 'neutral';
  reason: string;
  ageMinutes: number | null;
}

const BULLISH_DIRECTIONS = new Set([
  'bullish_continuation',
  'bearish_to_bullish',
  'bullish_breakout',
]);

const BEARISH_DIRECTIONS = new Set([
  'bearish_continuation',
  'bullish_to_bearish',
  'bearish_breakout',
]);

const STATUS_SORT_WEIGHT: Record<IntradayDirectionStatus, number> = {
  休市等待: 7,
  行情延迟: 6,
  多头确认: 1,
  空头确认: 1,
  多头观察: 2,
  空头观察: 2,
  多头延续: 3,
  空头延续: 3,
  震荡等待: 4,
  信号过期: 5,
  已经失效: 6,
  当日已收盘: 7,
  上个交易日信号: 8,
};

function result(
  status: IntradayDirectionStatus,
  direction: IntradayDirectionResult['direction'],
  entryState: IntradayDirectionResult['entryState'],
  reason: string,
  ageMinutes: number | null,
): IntradayDirectionResult {
  return { status, direction, entryState, reason, ageMinutes };
}

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function signalDirection(signal: RealtimePatternSignal): IntradayDirectionResult['direction'] {
  if (BULLISH_DIRECTIONS.has(signal.direction)) return 'call';
  if (BEARISH_DIRECTIONS.has(signal.direction)) return 'put';
  return 'neutral';
}

function signalEventTime(signal: RealtimePatternSignal): Date | null {
  const value = signal.stage === 'confirmed' && signal.confirmed_at ? signal.confirmed_at : signal.occurred_at;
  const event = new Date(value);
  return Number.isNaN(event.getTime()) ? null : event;
}

function marketParts(date: Date, marketType: MarketType): Record<string, string> {
  return Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: marketType === 'CN' ? 'Asia/Shanghai' : US_MARKET_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date).map((part) => [part.type, part.value]));
}

function dateKey(parts: Record<string, string>): string {
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function isValidTradingDate(value: string | null | undefined): value is string {
  return Boolean(value && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

export function intradayDirectionSortValue(status: IntradayDirectionResult | null): number {
  return status ? STATUS_SORT_WEIGHT[status.status] : 9;
}

export function calculateIntradayDirection(
  quote: RealtimeQuote | null | undefined,
  marketType: MarketType,
  now = new Date(),
): IntradayDirectionResult | null {
  if (Number.isNaN(now.getTime())) return null;
  if (!['CN', 'US'].includes(marketType) || !quote?.available || !finite(quote.last_price)) return null;

  const trend = quote.trend_1m;
  const pattern = quote.pattern_1m;
  if (!trend || !pattern || trend.state === 'insufficient' || trend.effective_period < trend.minimum_period) return null;

  const nowParts = marketParts(now, marketType);
  const minutesAfterMidnight = Number(nowParts.hour) * 60 + Number(nowParts.minute);
  const closeMinutes = marketType === 'CN' ? 15 * 60 : 16 * 60;
  const closed = quote.session_close ? now.getTime() >= Date.parse(quote.session_close) : minutesAfterMidnight >= closeMinutes;
  if (closed) return result('当日已收盘', 'neutral', 'closed', '最近交易日已收盘，仅展示历史结构。', null);
  if (quote.market_open === false || minutesAfterMidnight < 9 * 60 + 30
    || (marketType === 'CN' && minutesAfterMidnight >= 11 * 60 + 30 && minutesAfterMidnight < 13 * 60)) {
    return result('休市等待', 'neutral', 'neutral', '当前不在常规交易时段。', null);
  }
  const observed = Date.parse(quote.event_time || '');
  const received = Date.parse(quote.received_at || '');
  if (quote.timestamp_kind === 'received' || ![observed, received].every(Number.isFinite) || now.getTime() - observed > 90_000
    || now.getTime() - received > 90_000 || observed - now.getTime() > 5_000 || received - now.getTime() > 5_000) {
    return result('行情延迟', 'neutral', 'neutral', '行情时间缺失或延迟，暂停实时方向判断。', null);
  }
  if (trend.bar_time && (now.getTime() - Date.parse(trend.bar_time) > 180_000 || Date.parse(trend.bar_time) > now.getTime())) {
    return result('行情延迟', 'neutral', 'neutral', '分钟趋势未及时更新，暂停实时方向判断。', null);
  }
  if (pattern.status !== 'active' || !pattern.signal) {
    return result('震荡等待', 'neutral', 'neutral', '当前没有有效的一分钟形态，等待结构和方向进一步明确。', null);
  }

  const signal = pattern.signal;
  const event = signalEventTime(signal);
  if (!event || !isValidTradingDate(signal.trading_date) || Number.isNaN(now.getTime())) return null;

  if (event.getTime() > now.getTime() + 5_000) return null;
  const elapsedMinutes = Math.max(0, (now.getTime() - event.getTime()) / 60_000);
  const ageMinutes = Math.floor(elapsedMinutes);
  const direction = signalDirection(signal);
  const currentTradingDate = dateKey(nowParts);

  if (signal.trading_date < currentTradingDate) {
    return result('上个交易日信号', direction, 'expired', '该形态不属于当前市场交易日期，仅作为历史结构参考。', ageMinutes);
  }
  if (signal.trading_date > currentTradingDate) return null;

  if (finite(signal.invalidation_price)) {
    const bullishInvalid = direction === 'call' && quote.last_price < signal.invalidation_price;
    const bearishInvalid = direction === 'put' && quote.last_price > signal.invalidation_price;
    if (bullishInvalid || bearishInvalid) {
      return result('已经失效', direction, 'invalid', '最新价已经突破形态失效位，原有方向结构不再成立。', ageMinutes);
    }
  }

  const fresh = elapsedMinutes <= INTRADAY_ENTRY_MAX_AGE_MINUTES;
  const bullishTrend = trend.state === 'above' && trend.streak >= 2;
  const bearishTrend = trend.state === 'below' && trend.streak >= 2;

  if (direction === 'call' && signal.stage === 'confirmed' && bullishTrend && fresh) {
    return result('多头确认', direction, 'fresh', '看涨形态已确认，一分钟趋势连续位于均线上方。', ageMinutes);
  }
  if (direction === 'put' && signal.stage === 'confirmed' && bearishTrend && fresh) {
    return result('空头确认', direction, 'fresh', '看跌形态已确认，一分钟趋势连续位于均线下方。', ageMinutes);
  }
  if (direction === 'call' && signal.stage === 'warning' && bullishTrend && fresh) {
    return result('多头观察', direction, 'watch', '看涨形态处于观察阶段，一分钟趋势连续位于均线上方。', ageMinutes);
  }
  if (direction === 'put' && signal.stage === 'warning' && bearishTrend && fresh) {
    return result('空头观察', direction, 'watch', '看跌形态处于观察阶段，一分钟趋势连续位于均线下方。', ageMinutes);
  }
  if (direction === 'call' && signal.stage === 'confirmed' && bullishTrend && !fresh) {
    return result('多头延续', direction, 'extended', '多头结构仍有效，但信号已经延续较久，不宜直接追高。', ageMinutes);
  }
  if (direction === 'put' && signal.stage === 'confirmed' && bearishTrend && !fresh) {
    return result('空头延续', direction, 'extended', '空头结构仍有效，但信号已经延续较久，不宜直接追空。', ageMinutes);
  }
  if (direction !== 'neutral' && signal.stage === 'warning' && !fresh) {
    return result('信号过期', direction, 'expired', '形态仍未确认，已超过适合依据该信号新开仓的观察窗口。', ageMinutes);
  }

  return result('震荡等待', 'neutral', 'neutral', '趋势强度、形态阶段或方向一致性尚未满足观察条件。', ageMinutes);
}
