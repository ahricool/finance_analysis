import type { CryptoKline } from '@/types/binance';
import type { CryptoSnapshot } from '@/types/crypto';
import { bucketOperations, type TradeMarker } from '@/lib/tradeMarkers';

export function btcMarkers(signals: CryptoSnapshot[], candles: CryptoKline[], strategyKey?: string): TradeMarker[] {
  const selected = strategyKey ? signals.filter(signal => signal.strategyKey === strategyKey) : signals;
  const operations = selected
    .filter(signal => signal.action === 'BUY' || signal.action === 'EXIT')
    .map(signal => ({
      executedAt: Date.parse(signal.evaluatedAt),
      side: signal.action === 'BUY' ? 'BUY' : 'SELL',
      price: signal.price,
      label: `${signal.strategyKey} ${signal.action}`,
    }));
  const buckets = candles.map(row => ({ start: Date.parse(row.openTime), end: Date.parse(row.closeTime) }));
  return bucketOperations(operations, buckets).map(marker => ({
    ...marker,
    strategyKey: strategyKey ?? selected[0]?.strategyKey,
  }));
}
