import { getActivePinia } from 'pinia';
import {
  DEFAULT_DISPLAY_TIMEZONE,
  type DisplayTimezone,
  useTimezoneStore,
} from '@/stores/timezoneStore';

export function getDisplayTimezone(): DisplayTimezone {
  if (!getActivePinia()) return DEFAULT_DISPLAY_TIMEZONE;
  return useTimezoneStore().displayTimezone;
}

export const toUtcIsoString = (value: string | Date): string => {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString();
};

/** Convert a datetime-local value in an IANA timezone to an ISO UTC instant. */
export const localDateTimeToUtcIso = (
  value: string,
  timeZone: DisplayTimezone = getDisplayTimezone(),
): string => {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return value;

  const [, year, month, day, hour, minute] = match;
  const targetUtc = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute));
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  });

  const offsetAt = (timestamp: number): number => {
    const parts = Object.fromEntries(
      formatter.formatToParts(new Date(timestamp)).map((part) => [part.type, part.value]),
    );
    const representedUtc = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    );
    return representedUtc - timestamp;
  };

  const firstPass = targetUtc - offsetAt(targetUtc);
  return new Date(targetUtc - offsetAt(firstPass)).toISOString();
};

export const formatDateTimeInDisplayTimezone = (value?: string | null): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: getDisplayTimezone(),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).format(date);
};

export const formatDateTime = formatDateTimeInDisplayTimezone;

export const formatDateOnly = (value?: string | null): string => {
  if (!value) return '—';
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (dateOnly) return `${dateOnly[1]}-${dateOnly[2]}-${dateOnly[3]}`;
  return value;
};

export const formatDate = (value?: string | null): string => {
  if (!value) return '—';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDateOnly(value);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: getDisplayTimezone(),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
};

export const toDateInputValue = (date: Date): string => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

function shiftDateOnly(value: string, days: number): string {
  const [year, month, day] = value.split('-').map(Number);
  const shifted = new Date(Date.UTC(year, (month || 1) - 1, (day || 1) + days));
  const y = shifted.getUTCFullYear();
  const m = `${shifted.getUTCMonth() + 1}`.padStart(2, '0');
  const d = `${shifted.getUTCDate()}`.padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Returns the date N days ago as YYYY-MM-DD in the current display timezone.
 * Consistent with getTodayInShanghai() so both ends of the date range
 * are expressed in the same timezone that the API date filters receive.
 */
export const getRecentStartDate = (days: number): string => {
  return shiftDateOnly(getTodayInDisplayTimezone(), -days);
};

/**
 * Returns today's date as YYYY-MM-DD in the current display timezone.
 */
export const getTodayInDisplayTimezone = (): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: getDisplayTimezone() }).format(new Date());

export const getTodayInShanghai = getTodayInDisplayTimezone;

export const formatReportType = (value?: string): string => {
  if (!value) return '—';
  if (value === 'simple') return '普通';
  if (value === 'detailed') return '标准';
  return value;
};
