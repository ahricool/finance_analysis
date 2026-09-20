import { describe, expect, it } from 'vitest';
import { btcMarkers } from '../btcMarkers';
import type { CryptoSnapshot } from '@/types/crypto';
import type { CryptoKline } from '@/types/binance';
const candle = (openTime: string, closeTime: string) => ({ openTime, closeTime } as CryptoKline);
const signal = (action: string, evaluatedAt: string) => ({ action, evaluatedAt, price: '100' } as CryptoSnapshot);

describe('BTC signal close-boundary placement', () => {
  it.each([
    ['1m', '2026-09-01T10:14:00Z'],
    ['5m', '2026-09-01T10:10:00Z'],
    ['15m', '2026-09-01T10:00:00Z'],
  ])('%s anchors BUY and EXIT to the candle closing at evaluatedAt', (_interval, open) => {
    const close = '2026-09-01T10:15:00Z';
    const rows = [candle(open!, close), candle(close, '2026-09-01T10:30:00Z')];
    const markers = btcMarkers(['BUY', 'EXIT', 'WAIT', 'HOLD'].map(action => signal(action, close)), rows);
    expect(markers.map(item => item.signal.action)).toEqual(['BUY', 'EXIT']);
    expect(markers.map(item => item.timestamp)).toEqual([Date.parse(open!), Date.parse(open!)]);
    expect(btcMarkers([signal('BUY', open!)], rows)).toEqual([]);
  });

  it.each([
    ['1h', '2026-09-01T10:00:00Z', '2026-09-01T11:00:00Z', '2026-09-01T12:00:00Z'],
    ['4h', '2026-09-01T08:00:00Z', '2026-09-01T12:00:00Z', '2026-09-01T16:00:00Z'],
    ['1d', '2026-09-01T00:00:00Z', '2026-09-02T00:00:00Z', '2026-09-03T00:00:00Z'],
    ['1w', '2026-08-31T00:00:00Z', '2026-09-07T00:00:00Z', '2026-09-14T00:00:00Z'],
    ['1M', '2026-09-01T00:00:00Z', '2026-10-01T00:00:00Z', '2026-11-01T00:00:00Z'],
  ])('%s uses loaded boundaries for interior and exact-close signals', (_interval, open, close, nextClose) => {
    const rows = [candle(open!, close!), candle(close!, nextClose!)];
    const markers = btcMarkers([signal('BUY', '2026-09-01T10:15:00Z'), signal('EXIT', close!)], rows);
    expect(markers.map(item => item.timestamp)).toEqual([Date.parse(open!), Date.parse(open!)]);
    expect(markers[1]?.signal.evaluatedAt).toBe(close);
  });

  it('remaps the same strategy close when switching the loaded interval', () => {
    const signals = [signal('BUY', '2026-09-01T10:15:00Z'), signal('EXIT', '2026-09-01T10:30:00Z')];
    const quarters = [candle('2026-09-01T10:00:00Z', signals[0]!.evaluatedAt), candle(signals[0]!.evaluatedAt, signals[1]!.evaluatedAt)];
    expect(btcMarkers(signals, quarters).map(item => item.timestamp)).toEqual(quarters.map(row => Date.parse(row.openTime)));
    const hour = candle('2026-09-01T10:00:00Z', '2026-09-01T11:00:00Z');
    expect(btcMarkers(signals, [hour]).map(item => item.timestamp)).toEqual([Date.parse(hour.openTime), Date.parse(hour.openTime)]);
  });
});
