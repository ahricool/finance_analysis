export type TrendMarket = 'CN' | 'US';
export type TrendRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
export type TrendState = 'IDLE' | 'WATCHING' | 'CANDIDATE' | 'TRENDING' | 'WEAKENING' | 'BROKEN';

export interface TrendFeatures {
  trendQuality?: number | null;
  trendAcceleration?: number | null;
  signedEfficiencyRatio10D?: number | null;
  ma10: number;
  ma20: number;
  ma10Slope: number;
  ma20Slope: number;
  trendCandidate: boolean;
  rawWeightedSlope: number;
  weightedSlopePercentile: number;
  weightedR2: number;
  return5D: number;
  return10D: number;
  return20D: number;
  return10DPercentile: number;
  return20DPercentile: number;
  drawdown20D: number;
  rs5D: number;
  rs10D: number;
  rs20D: number;
  breakout10D: boolean;
  breakout20D: boolean;
  breakoutDistance: number;
  volumeRatio: number;
  distanceFromMa20: number;
  priorCompression: boolean;
  compressionBreakout: boolean;
  trendResume: boolean;
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
  referencePrice: number;
  atr: number;
  reasons: string[];
  trendLifecycle?: 'IGNITION' | 'EMERGING' | 'EXPANSION' | 'MATURE' | 'EXHAUSTION' | 'BROKEN' | null;
  fragilityScore?: number | null;
  fragilityBreakdown?: Record<string, number | null> | null;
  trendDurationDays: number | null;
  generatedAt: string;
}

export type TrendCandidate = Pick<TrendSnapshot, 'code' | 'name' | 'rank' | 'state' | 'alphaScore'>;

// Only scalar columns used by the table, its sort menu and preview comparisons.
export interface TrendRankingSnapshot extends Pick<TrendSnapshot,
  'code' | 'name' | 'rank' | 'state' | 'trendDurationDays' | 'trendLifecycle' | 'fragilityScore' |
  'alphaScore' | 'trendScore' | 'rsScore' | 'breakoutScore' | 'setup' | 'atr' |
  'referencePrice'> {
  features: Pick<TrendFeatures, 'return5D' | 'return10D' | 'return20D' | 'volumeRatio' | 'distanceFromMa20'>;
  rankChange1D: number | null;
  rankChange3D: number | null;
  rankChange5D: number | null;
}

export interface TrendSummary {
  market: TrendMarket;
  tradeDate: string;
  universeKey: string;
  benchmarkCode: string;
  marketRegime: TrendRegime;
  marketScore: number;
  universeSize: number;
  dataReadyCount: number;
  dataCoverage: number;
  rankableCount: number;
  candidateCount: number;
  warnings: string[];
  features: { [key: string]: number | Record<string, number> | undefined; lifecycleCounts?: Record<string, number>; highFragilityCount?: number };
  scoreBreakdown: Record<string, number>;
  generatedAt: string;
}

export interface TrendChange {
  code: string;
  name: string;
  currentState: TrendState;
  currentRank: number;
  previousState: TrendState | null;
  previousRank: number | null;
  rankChange: number | null;
  trendScoreChange: number | null;
  rsScoreChange: number | null;
  alphaScoreChange: number | null;
}

export type TrendTransition = TrendChange;

export interface TrendRankingChanges {
  previousTradeDate: string | null;
  marketScoreChange: number | null;
  breadthScoreChange: number | null;
  newCandidates: TrendChange[];
  newWeakening: TrendChange[];
  newBroken: TrendChange[];
  transitions: TrendTransition[];
  movers: TrendChange[];
}

export interface TrendRankingResponse extends TrendSummary {
  items: TrendRankingSnapshot[];
  candidates: TrendCandidate[];
  changes?: TrendRankingChanges | null;
}
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

export type TrendPreviewStatus = 'completed' | 'failed' | 'incomplete' | string;

export interface TrendPreviewResponse extends Omit<TrendSummary, 'generatedAt'> {
  status: TrendPreviewStatus;
  previewTime: string | null;
  dataAsOf: string | null;
  provider: string | null;
  quoteCount?: number;
  snapshotCount?: number;
  snapshots: TrendSnapshot[];
  generatedAt?: string | null;
  elapsedSeconds?: number;
}

/** Metadata only; complete strategy rows are fetched separately on entering Preview. */
export interface TrendPreviewStatusResponse {
  status: string;
  market: TrendMarket;
  tradeDate: string;
  previewTime: string | null;
  dataAsOf: string | null;
  provider: string | null;
  snapshotCount: number;
  warnings: string[];
}


export interface TrendStateHistoryCell {
  rank: number;
  state: TrendState;
  alphaScore: number | null;
  trendScore: number | null;
  rsScore: number | null;
  fragilityScore: number | null;
  trendDurationDays: number | null;
}

export interface TrendStateHistoryResponse {
  market: TrendMarket;
  anchorDate: string | null;
  dates: string[];
  officialCount: number;
  previewDate: string | null;
  previewTime: string | null;
  generatedAt: string | null;
  warnings: string[];
  items: Array<{ code: string; name: string; currentRank: number; history: Array<TrendStateHistoryCell | null> }>;
}
