import type { Candle } from '@/api/contracts';
import type { ChartPeriod } from '@/components/market-data/instrument-table/state';

const day = 86_400_000;
export function nativeInterval(period: ChartPeriod) {
  return ['1m', '5m', '15m', '1h'].includes(period) ? '1m' : '1d';
}
function bounds(timestamp: number, period: ChartPeriod) {
  const date = new Date(timestamp);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (period === '1y') return [Date.UTC(year, 0), Date.UTC(year + 1, 0)] as const;
  if (period === '1M') return [Date.UTC(year, month), Date.UTC(year, month + 1)] as const;
  if (period === '1w') {
    const start = timestamp - ((date.getUTCDay() + 6) % 7) * day;
    return [start, start + 7 * day] as const;
  }
  const size = period === '1h' ? 3600000 : period === '15m' ? 900000 : 300000;
  const start = Math.floor(timestamp / size) * size;
  return [start, start + size] as const;
}
export function aggregateContracts(candles: Candle[], period: ChartPeriod, now: number) {
  const step = nativeInterval(period) === '1m' ? 60_000 : day;
  const bars: Candle[] = [];
  let current: Candle | null = null;
  let group: Candle | undefined;
  let expected = 0;
  for (const bar of candles) {
    const [start, end] = bounds(bar.timestamp, period);
    if (bar.closed === false && bar.timestamp + step <= now) {
      group = undefined;
      continue;
    }
    if (bar.timestamp === start) {
      group = { ...bar, timestamp: start };
    } else if (group?.timestamp === start && bar.timestamp === expected) {
      group.high = Math.max(group.high, bar.high);
      group.low = Math.min(group.low, bar.low);
      group.close = bar.close;
      group.volume += bar.volume;
      group.turnover += bar.turnover;
    } else {
      group = undefined;
    }
    expected = bar.timestamp + step;
    if (!group) continue;
    if (expected === end && end <= now && bar.closed !== false) bars.push(group);
    else if (expected >= now && start <= now && now < end) current = group;
  }
  return { bars, current };
}
