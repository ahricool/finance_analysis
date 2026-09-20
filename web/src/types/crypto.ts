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
export interface CryptoOverview {
  symbol: 'BTCUSDT'; strategy: CryptoSnapshot | null; state: CryptoState;
}
