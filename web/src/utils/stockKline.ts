import type { DailyBar } from '@/api/marketData';

export type StockKlinePeriod = '1d' | '1w' | '1M';

/** Exchange trading dates, independent of the browser's timezone. Weeks start Monday. */
export function stockPeriodKey(date: string, period: StockKlinePeriod): string {
  if (period === '1d') return date;
  if (period === '1M') return date.slice(0, 7);
  const day = new Date(`${date}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
  return day.toISOString().slice(0, 10);
}

/** Never fill missing sessions. Label each bucket with its first available trading date. */
export function aggregateStockBars(rows: DailyBar[], period: StockKlinePeriod): DailyBar[] {
  const groups = new Map<string, DailyBar>();
  for (const row of [...rows].sort((a, b) => a.tradeDate.localeCompare(b.tradeDate))) {
    const key = stockPeriodKey(row.tradeDate, period);
    const bar = groups.get(key);
    if (!bar) groups.set(key, { ...row });
    else {
      bar.high = Math.max(bar.high, row.high);
      bar.low = Math.min(bar.low, row.low);
      bar.close = row.close;
      bar.volume += row.volume;
      bar.amount = bar.amount == null || row.amount == null ? null : bar.amount + row.amount;
    }
  }
  return [...groups.values()];
}
