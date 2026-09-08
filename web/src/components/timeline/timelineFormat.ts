import type { CalendarType, Category, Importance, TimelineItem } from '@/api/timeline';
import { getDisplayTimezone, getTodayInDisplayTimezone } from '@/utils/format';

export const marketNames: Record<string, string> = { CN: 'A股', US: '美股', HK: '港股' };
export const importanceNames: Record<Importance, string> = {
  low: 'Low', normal: 'Normal', high: 'High', critical: 'Critical',
};
const sessionNames: Record<string, string> = {
  bmo: '盘前 BMO', amc: '盘后 AMC', during_market: '盘中',
};

export function kindLabel(item: TimelineItem): string {
  if (item.category === 'news') return '新闻';
  if (item.category === 'analysis') return '市场分析';
  return item.calendarType === 'earnings' ? '财报' : '宏观';
}

export function marketLabel(market: string | null): string {
  if (!market) return '';
  return marketNames[market] ?? market;
}

/** Session labels are only meaningful when the provider actually reported one. */
export function sessionLabel(value: unknown): string {
  return typeof value === 'string' ? (sessionNames[value] ?? '') : '';
}

/** YYYY-MM-DD of an instant in the user's display timezone. */
export function dayKey(eventTime: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: getDisplayTimezone(), year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(eventTime));
}

export function dayHeading(key: string): string {
  const [year, month, day] = key.split('-').map(Number);
  const now = Number(getTodayInDisplayTimezone().slice(0, 4));
  const short = `${month}月${day}日`;
  return year === now ? short : `${year}年${short}`;
}

export function shortDate(eventTime: string): string {
  const [, month, day] = dayKey(eventTime).split('-');
  return `${Number(month)}/${Number(day)}`;
}

export function clockTime(eventTime: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: getDisplayTimezone(), hour: '2-digit', minute: '2-digit', hour12: false, hourCycle: 'h23',
  }).format(new Date(eventTime));
}

function calendarDaysFromToday(key: string): number {
  const toUtc = (value: string) => {
    const [year, month, day] = value.split('-').map(Number);
    return Date.UTC(year, month - 1, day);
  };
  return Math.round((toUtc(key) - toUtc(getTodayInDisplayTimezone())) / 86_400_000);
}

/**
 * Purely informational distance from today. Ordering and filtering never depend on it,
 * and trading-day labels are only used when the backend already computed them.
 */
export function distanceLabel(item: TimelineItem): string {
  const tradingDays = item.detailPayload.tradingDaysToEvent;
  if (typeof tradingDays === 'number' && tradingDays > 0) return `T-${tradingDays}`;
  const days = calendarDaysFromToday(dayKey(item.eventTime));
  if (days === 0) return '今天';
  if (days === 1) return '明天';
  if (days > 1) return `${days}天后`;
  return `${-days}天前`;
}

export function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== '' && value !== 'unknown';
}

export function formatEps(value: unknown): string {
  return typeof value === 'number' ? `$${value.toFixed(2)}` : '';
}

export function formatSurprise(value: unknown): string {
  return typeof value === 'number' ? `${value > 0 ? '+' : ''}${value.toFixed(1)}%` : '';
}

export const tabQuery: Record<string, { category?: Category; calendar_type?: CalendarType }> = {
  all: {},
  earnings: { category: 'event', calendar_type: 'earnings' },
  macro: { category: 'event', calendar_type: 'macro' },
  news: { category: 'news' },
  analysis: { category: 'analysis' },
};
