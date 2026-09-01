export type TrendMarket = 'CN' | 'US';
export type TrendRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
export type TrendState = 'IDLE' | 'WATCHING' | 'CANDIDATE' | 'ENTRY' | 'PYRAMIDING' | 'HOLDING' | 'WEAKENING' | 'REDUCE' | 'EXIT';
export type TrendAction = 'WATCH' | 'PENDING_ENTRY' | 'PENDING_ADD' | 'PENDING_REDUCE' | 'PENDING_EXIT' | 'ENTRY' | 'ADD' | 'HOLD' | 'STOP_ADD' | 'REDUCE' | 'EXIT' | 'EXPOSURE_BLOCKED';

export interface TrendFeatures {
  ma10: number;
  ma20: number;
  ma60: number;
  ma20Slope: number;
  trendCandidate: boolean;
  rawWeightedSlope: number;
  weightedSlopePercentile: number;
  weightedR2: number;
  return20D: number;
  return60D: number;
  return20DPercentile: number;
  return60DPercentile: number;
  drawdown20D: number;
  drawdown60D: number;
  rs20D: number;
  rs60D: number;
  breakout20D: boolean;
  breakout55D: boolean;
  breakoutDistance: number;
  volumeRatio: number;
  distanceFromMa20: number;
  priorCompression: boolean;
  compressionBreakout: boolean;
  [key: string]: unknown;
}

export interface TrendSnapshot {
  id: number;
  market: TrendMarket;
  tradeDate: string;
  code: string;
  name: string;
  universeKey: string;
  marketRegime: TrendRegime;
  marketScore: number;
  rank: number;
  trendScore: number;
  rsScore: number;
  breakoutScore: number;
  alphaScore: number;
  features: TrendFeatures;
  scoreBreakdown: Record<string, unknown>;
  setup: string;
  state: TrendState;
  action: TrendAction;
  referencePrice: number;
  atr: number;
  entryPrice: number | null;
  signalDate: string | null;
  signalPrice: number | null;
  pendingAction: 'ENTRY' | 'ADD' | 'REDUCE' | 'EXIT' | null;
  pendingSince: string | null;
  pendingRegime: TrendRegime | null;
  pendingMaxExposure: number | null;
  openedAt: string | null;
  lastAddPrice: number | null;
  highestClose: number | null;
  initialStop: number | null;
  trailingStop: number | null;
  nextAddPrice: number | null;
  exitLevel: number | null;
  units: number;
  suggestedInitialWeight: number | null;
  suggestedMaxWeight: number | null;
  reasons: string[];
  generatedAt: string;
}

export interface TrendSummary {
  market: TrendMarket;
  tradeDate: string;
  universeKey: string;
  benchmarkCode: string;
  marketRegime: TrendRegime;
  marketScore: number;
  suggestedMaxExposure: number;
  universeSize: number;
  dataReadyCount: number;
  dataCoverage: number;
  rankableCount: number;
  candidateCount: number;
  entryCount: number;
  addCount: number;
  holdCount: number;
  reduceCount: number;
  exitCount: number;
  warnings: string[];
  features: Record<string, number>;
  scoreBreakdown: Record<string, number>;
  generatedAt: string;
}

export interface TrendRankingResponse extends TrendSummary { items: TrendSnapshot[] }
export interface TrendCandidatesResponse { market: TrendMarket; tradeDate: string; summary: TrendSummary | null; items: TrendSnapshot[] }
export interface TrendDatesResponse { market: TrendMarket; latest: string | null; items: string[] }
export interface TrendDetailResponse {
  market: TrendMarket;
  tradeDate?: string;
  metadata: { market: TrendMarket; code: string; name: string };
  latest: TrendSnapshot;
  history: TrendSnapshot[];
  marketContext: TrendSummary | null;
}
export interface TrendRunAccepted { taskId: string; status: 'pending'; market: TrendMarket; tradeDate: string | null }
