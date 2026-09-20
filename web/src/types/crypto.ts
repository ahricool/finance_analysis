export interface CryptoSnapshot {
  strategyKey: string;
  symbol: 'BTCUSDT'; evaluatedAt: string; regime: 'BULL' | 'BEAR' | 'RANGE' | 'UNKNOWN';
  setup: 'BREAKOUT' | 'NONE'; action: 'BUY' | 'WAIT' | 'HOLD' | 'EXIT'; price: string;
  // Digit/letter boundaries follow the shared camelcase-keys API adapter.
  ema201H: string | null; ema501H: string | null; ema2015M: string | null;
  breakoutLevel15M: string | null; volumeRatio15M: string | null; atr1415M: string | null;
  initialStop: string | null; trailingStop: string | null;
  positionBefore: string | null; positionAfter: string | null; positionDelta: string | null;
  averageEntryPrice: string | null;
  positionState: 'FLAT' | 'LONG'; reason: string;
}
export interface CryptoState {
  strategyKey: string;
  symbol: 'BTCUSDT'; positionState: 'FLAT' | 'LONG'; entryPrice: string | null;
  positionPct: string; averageEntryPrice: string | null;
  entryTime: string | null; highestPriceSinceEntry: string | null;
  initialStop: string | null; trailingStop: string | null; updatedAt: string | null;
}
export interface CryptoOverview {
  strategyKey: string;
  symbol: 'BTCUSDT'; strategy: CryptoSnapshot | null; state: CryptoState;
}

export interface CryptoExecution {
  evaluatedAt: string; price: string; positionBefore: string; positionAfter: string;
  positionDelta: string; action: string; reason: string;
}
export interface CryptoTrade {
  entryTime: string; exitTime: string; holdingSeconds: number;
  averageEntryPrice: string; exitPrice: string; realizedReturn: string;
}
export interface CryptoPerformance {
  strategyKey: string; displayName: string; symbol: string;
  runningDays: string; annualizedReturn: string | null; breakeven: number; equityPointsTotal: number;
  performanceStartAt: string | null; performanceEndAt: string | null;
  currentPosition: { positionPct: string; averageEntryPrice: string | null };
  executionCount: number; closedTrades: number; wins: number; losses: number;
  winRate: string | null; averageTradeReturn: string | null; totalReturn: string; maxDrawdown: string;
  bestTrade: string | null; worstTrade: string | null;
  recentExecutions: CryptoExecution[]; recentTrades: CryptoTrade[];
  equityCurve: { evaluatedAt: string; equity: string; drawdown: string }[];
}

export interface CryptoStrategyDefinition {
  strategyKey: string; displayName: string; enabled: boolean; currentPosition: string;
  latestAction: string | null; latestEvaluatedAt: string | null;
}
export type CryptoPerformanceSummary = Pick<CryptoPerformance,
  'strategyKey' | 'displayName' | 'currentPosition' | 'totalReturn' | 'annualizedReturn' |
  'maxDrawdown' | 'winRate' | 'closedTrades' | 'runningDays' | 'performanceStartAt' | 'performanceEndAt'>;
