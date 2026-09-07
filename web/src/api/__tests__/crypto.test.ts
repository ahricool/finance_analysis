import { describe, expect, it } from 'vitest';
import { parseCryptoMessage, cryptoWebSocketUrl } from '../crypto';

describe('BTC API transport', () => {
  it('converts the unified backend state and preserves decimal strings', () => {
    const data = parseCryptoMessage(JSON.stringify({ type: 'state', market: {
      symbol: 'BTCUSDT', stream_mode: 'http_fallback', latest_candle: { close: '123.123456789012', open_time: '2026-09-01T00:00:00Z' },
      strategy_latest_state: { ema20_1h: '100.123456789012' },
    } }));
    expect(data?.latestCandle?.close).toBe('123.123456789012');
    expect(data?.strategyLatestState?.ema201H).toBe('100.123456789012');
    expect(parseCryptoMessage('{"type":"other"}')).toBeNull();
    expect(cryptoWebSocketUrl()).toContain('/api/v1/crypto/ws');
    expect(cryptoWebSocketUrl()).not.toContain('binance');
  });
});
