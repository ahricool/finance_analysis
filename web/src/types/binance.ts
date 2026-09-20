export const BINANCE_INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d', '1w', '1M'] as const;
export type BinanceInterval = typeof BINANCE_INTERVALS[number];
export interface CryptoKline {
  symbol: 'BTCUSDT'; interval: BinanceInterval; source: 'binance';
  openTime: string; closeTime: string;
  open: string; high: string; low: string; close: string; volume: string;
  quoteVolume: string; tradeCount: number; takerBuyVolume: string; takerBuyQuoteVolume: string;
  closed: boolean;
}
