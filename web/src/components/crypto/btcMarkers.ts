import type { CryptoKline, BinanceInterval } from '@/types/binance';
import type { CryptoSnapshot } from '@/types/crypto';

// Use the candles already on screen, including Binance's real month/week boundaries.
export function btcMarkers(signals: CryptoSnapshot[], candles: CryptoKline[], interval: BinanceInterval) {
  return signals.filter(signal => signal.action === 'BUY' || signal.action === 'EXIT').flatMap(signal => {
    const timestamp = Date.parse(signal.evaluatedAt);
    const candle = candles.find(row => Date.parse(row.openTime) <= timestamp && timestamp < Date.parse(row.closeTime));
    if (!candle) return [];
    return [{ signal, timestamp: ['1m', '5m', '15m'].includes(interval) ? timestamp : Date.parse(candle.openTime) }];
  });
}
