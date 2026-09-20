import { describe, expect, it } from 'vitest';
import { btcMarkers } from '../btcMarkers';
import type { CryptoSnapshot } from '@/types/crypto';
import type { CryptoKline, BinanceInterval } from '@/types/binance';
const candle = (openTime: string, closeTime: string) => ({ openTime, closeTime } as CryptoKline);
const signal = (action: string, evaluatedAt: string) => ({ action, evaluatedAt, price: '100' } as CryptoSnapshot);
describe('BTC signal placement', () => {
  it('only displays BUY/EXIT and keeps exact timestamps on short periods', () => {
    const rows = [candle('2026-09-01T10:00:00Z','2026-09-01T11:00:00Z')];
    const signals = ['BUY','EXIT','WAIT','HOLD'].map(action => signal(action,'2026-09-01T10:15:00Z'));
    for (const interval of ['1m','5m','15m'] as BinanceInterval[]) {
      const markers = btcMarkers(signals, rows, interval);
      expect(markers.map(item => item.signal.action)).toEqual(['BUY','EXIT']);
      expect(markers[0]?.timestamp).toBe(Date.parse('2026-09-01T10:15:00Z'));
    }
  });
  it.each(['1h','4h','1d','1w','1M'] as BinanceInterval[])('maps %s to containing Binance candle without rounding month/week boundaries', interval => {
    const rows = [candle('2026-09-01T00:00:00Z','2026-10-01T00:00:00Z'), candle('2026-10-01T00:00:00Z','2026-11-01T00:00:00Z')];
    const markers = btcMarkers([signal('BUY','2026-09-20T10:15:00Z'),signal('EXIT','2026-10-01T00:00:00Z'),signal('BUY','2026-08-01T00:00:00Z')], rows, interval);
    expect(markers.map(item => item.timestamp)).toEqual(rows.map(row => Date.parse(row.openTime)));
  });
});
