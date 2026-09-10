import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import {
  formatCompactDateTimeInDisplayTimezone,
  formatDateOnly,
  formatDateTimeInDisplayTimezone,
  formatFullDateTimeWithTimezone,
  formatRelativeAge,
  localDateTimeToUtcIso,
  toUtcIsoString,
} from '../format';
import { useTimezoneStore } from '../../stores/timezoneStore';

describe('timezone display formatting', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('formats the same UTC instant differently by selected timezone', () => {
    const store = useTimezoneStore();
    const value = '2026-06-10T01:30:00.000Z';

    store.setDisplayTimezone('Asia/Shanghai');
    expect(formatDateTimeInDisplayTimezone(value)).toContain('2026/06/10 09:30');

    store.setDisplayTimezone('America/New_York');
    expect(formatDateTimeInDisplayTimezone(value)).toContain('2026/06/09 21:30');
  });

  it('uses New York daylight saving rules instead of fixed UTC-5', () => {
    const store = useTimezoneStore();
    store.setDisplayTimezone('America/New_York');

    expect(formatDateTimeInDisplayTimezone('2026-06-10T14:00:00.000Z')).toContain('10:00');
    expect(formatDateTimeInDisplayTimezone('2026-01-10T15:00:00.000Z')).toContain('10:00');
  });

  it('does not timezone-shift date-only values', () => {
    const store = useTimezoneStore();
    store.setDisplayTimezone('America/New_York');

    expect(formatDateOnly('2026-06-10')).toBe('2026-06-10');
  });

  it('serializes datetime inputs to UTC ISO strings for API payloads', () => {
    expect(toUtcIsoString('2026-06-10T09:30:00+08:00')).toBe('2026-06-10T01:30:00.000Z');
  });

  it('converts datetime-local values using the selected timezone and DST rules', () => {
    expect(localDateTimeToUtcIso('2026-06-10T09:30', 'Asia/Shanghai')).toBe('2026-06-10T01:30:00.000Z');
    expect(localDateTimeToUtcIso('2026-06-10T09:30', 'America/New_York')).toBe('2026-06-10T13:30:00.000Z');
    expect(localDateTimeToUtcIso('2026-01-10T09:30', 'America/New_York')).toBe('2026-01-10T14:30:00.000Z');
  });

  it('formats compact times for today and older days in the display timezone', () => {
    const store = useTimezoneStore();
    store.setDisplayTimezone('Asia/Shanghai');
    const now = new Date('2026-09-10T06:40:00.000Z');
    expect(formatCompactDateTimeInDisplayTimezone('2026-09-10T06:35:06.000Z', now)).toBe('14:35:06');
    expect(formatCompactDateTimeInDisplayTimezone('2026-09-09T10:31:00.000Z', now)).toBe('09-09 18:31');
    expect(formatFullDateTimeWithTimezone('2026-09-10T06:35:06.000Z')).toBe('2026-09-10 14:35:06 Asia/Shanghai');
    expect(formatRelativeAge('2026-09-10T06:23:00.000Z', now)).toBe('17 分钟');
  });
});
