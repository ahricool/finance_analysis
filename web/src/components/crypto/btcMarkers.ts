import type { CryptoKline } from '@/types/binance';
import type { CryptoSnapshot } from '@/types/crypto';

// evaluatedAt is the exclusive close boundary of the strategy candle.
// Anchor to the preceding candle's open, using Binance's actual week/month boundaries.
export function btcMarkers(signals: CryptoSnapshot[], candles: CryptoKline[]) {
  return signals.filter(signal => signal.action === 'BUY' || signal.action === 'EXIT').flatMap(signal => {
    const timestamp = Date.parse(signal.evaluatedAt);
    const candle = candles.find(row => Date.parse(row.openTime) < timestamp && timestamp <= Date.parse(row.closeTime));
    if (!candle) return [];
    return [{ signal, timestamp: Date.parse(candle.openTime) }];
  });
}
