import { describe, expect, it } from 'vitest';
import { btcMarkers } from '../btcMarkers';
import type { CryptoSnapshot } from '@/types/crypto';
import type { CryptoKline } from '@/types/binance';

const candle = (openTime: string, closeTime: string) => ({ openTime, closeTime } as CryptoKline);
const signal = (action: string, evaluatedAt: string) => ({ action, evaluatedAt, price: '100', strategyKey: 'btc_breakout_v1' } as CryptoSnapshot);

describe('BTC strategy BST markers', () => {
  it('maps BUY to B and EXIT to S on their candle bucket', () => {
    const rows = [candle('2026-09-01T10:00:00Z', '2026-09-01T10:15:00Z'), candle('2026-09-01T10:15:00Z', '2026-09-01T10:30:00Z')];
    const markers = btcMarkers([signal('BUY', '2026-09-01T10:15:00Z'), signal('EXIT', '2026-09-01T10:30:00Z')], rows);
    expect(markers.map(item => item.type)).toEqual(['B', 'S']);
    expect(markers.map(item => item.timestamp)).toEqual(rows.map(row => Date.parse(row.openTime)));
  });

  it('collapses BUY and EXIT in the same bucket to T', () => {
    const hour = candle('2026-09-01T10:00:00Z', '2026-09-01T11:00:00Z');
    const markers = btcMarkers([signal('BUY', '2026-09-01T10:15:00Z'), signal('EXIT', '2026-09-01T10:30:00Z')], [hour]);
    expect(markers).toHaveLength(1);
    expect(markers[0]?.type).toBe('T');
    expect(markers[0]?.timestamp).toBe(Date.parse(hour.openTime));
  });

  it('rebuckets when the loaded interval changes', () => {
    const signals = [signal('BUY', '2026-09-01T10:15:00Z'), signal('EXIT', '2026-09-01T10:30:00Z')];
    const quarters = [candle('2026-09-01T10:00:00Z', '2026-09-01T10:15:00Z'), candle('2026-09-01T10:15:00Z', '2026-09-01T10:30:00Z')];
    expect(btcMarkers(signals, quarters).map(item => item.type)).toEqual(['B', 'S']);
    expect(btcMarkers(signals, [candle('2026-09-01T10:00:00Z', '2026-09-01T11:00:00Z')]).map(item => item.type)).toEqual(['T']);
  });

  it('does not mix different strategies into one T marker', () => {
    const hour = candle('2026-09-01T10:00:00Z', '2026-09-01T11:00:00Z');
    const mixed = [
      { ...signal('BUY', '2026-09-01T10:15:00Z'), strategyKey: 'btc_breakout_v1' },
      { ...signal('EXIT', '2026-09-01T10:30:00Z'), strategyKey: 'other' },
    ] as CryptoSnapshot[];
    expect(btcMarkers(mixed, [hour], 'btc_breakout_v1').map(item => item.type)).toEqual(['B']);
  });
});
