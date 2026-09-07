export interface CryptoKline {
  symbol: 'BTCUSDT'; interval: '1m'; source: 'binance';
  openTime: string; closeTime: string;
  open: string; high: string; low: string; close: string; volume: string;
  quoteVolume: string; tradeCount: number; takerBuyVolume: string; takerBuyQuoteVolume: string;
  closed: boolean;
}
export interface CryptoSnapshot {
  symbol: 'BTCUSDT'; evaluatedAt: string; regime: 'BULL' | 'BEAR' | 'RANGE' | 'UNKNOWN';
  setup: 'BREAKOUT' | 'NONE'; action: 'BUY' | 'WAIT' | 'HOLD' | 'EXIT'; price: string;
  // Digit/letter boundaries follow the shared camelcase-keys API adapter.
  ema201H: string | null; ema501H: string | null; ema2015M: string | null;
  breakoutLevel15M: string | null; volumeRatio15M: string | null; atr1415M: string | null;
  initialStop: string | null; trailingStop: string | null;
  positionState: 'FLAT' | 'LONG'; reason: string;
}
export interface CryptoState {
  symbol: 'BTCUSDT'; positionState: 'FLAT' | 'LONG'; entryPrice: string | null;
  entryTime: string | null; highestPriceSinceEntry: string | null;
  initialStop: string | null; trailingStop: string | null; updatedAt: string | null;
}
export interface CryptoStatus {
  symbol: 'BTCUSDT'; enabled: boolean; ready: boolean;
  streamMode: 'websocket' | 'http_fallback'; websocketConnected: boolean;
  lastUpdateTime: string | null; lastWebsocketMessageTime: string | null; lastError: string | null;
  latestCandle: CryptoKline | null; recentClosed: CryptoKline[];
  strategyLatestState: CryptoSnapshot | null;
}
export interface CryptoOverview {
  symbol: 'BTCUSDT'; strategy: CryptoSnapshot | null; state: CryptoState; market: CryptoStatus;
}
