import type { DailyBar } from '@/api/marketData';
export function candle(open: number, close: number, low = Math.min(open, close) - 0.5, high = Math.max(open, close) + 0.5): DailyBar {
  return { tradeDate: '', open, close, low, high, volume: 100, amount: null };
}
export function dated(bars: DailyBar[]): DailyBar[] {
  return bars.map((bar, i) => ({ ...bar, tradeDate: new Date(Date.UTC(2026, 8, 1 + i)).toISOString().slice(0, 10) }));
}
export function falling() { return [110, 108, 106, 104, 102, 100].map(close => candle(close + 0.5, close)); }
export function mirror(bars: DailyBar[]): DailyBar[] {
  return bars.map(bar => ({ ...bar, open: 220 - bar.open, close: 220 - bar.close, high: 220 - bar.low, low: 220 - bar.high }));
}
export function engulfing() { return dated([...falling(), candle(100, 98), candle(97.8, 101, 97.5, 101.2)]); }
export function hammer() { return dated([...falling(), candle(98, 99, 94.5, 99.2)]); }
export function star() { return dated([...falling(), candle(100, 96), candle(96, 95.6, 95, 96.5), candle(95.5, 98.8, 95, 99)]); }
