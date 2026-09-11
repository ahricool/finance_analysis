export type TrendMarket = 'CN' | 'US';
export type TrendRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
export type TrendState = 'IDLE' | 'WATCHING' | 'CANDIDATE' | 'ENTRY' | 'PYRAMIDING' | 'HOLDING' | 'WEAKENING' | 'REDUCE' | 'EXIT';
export type TrendAction = 'WATCH' | 'PENDING_ENTRY' | 'PENDING_ADD' | 'PENDING_REDUCE' | 'PENDING_EXIT' | 'ENTRY' | 'ADD' | 'HOLD' | 'STOP_ADD' | 'REDUCE' | 'EXIT' | 'EXPOSURE_BLOCKED';

export interface TrendFeatures {
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
  trendDurationDays: number | null;
  generatedAt: string;
}

export type TrendCandidate = Pick<TrendSnapshot, 'code' | 'name' | 'rank' | 'state' | 'action' | 'alphaScore'>;

// Only scalar columns used by the table, its sort menu and preview comparisons.
export interface TrendRankingSnapshot extends Pick<TrendSnapshot,
  'code' | 'name' | 'rank' | 'state' | 'action' | 'pendingAction' | 'trendDurationDays' |
  'alphaScore' | 'trendScore' | 'rsScore' | 'breakoutScore' | 'setup' | 'atr' |
  'referencePrice' | 'signalDate' | 'signalPrice' | 'openedAt' | 'entryPrice' |
  'initialStop' | 'nextAddPrice' | 'exitLevel' | 'suggestedInitialWeight'> {
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

export interface TrendChange {
  code: string;
  name: string;
  currentState: TrendState;
  currentAction: TrendAction;
  currentPendingAction: TrendSnapshot['pendingAction'];
  currentRank: number;
  previousState: TrendState | null;
  previousAction: TrendAction | null;
  previousPendingAction: TrendSnapshot['pendingAction'] | null;
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
  newReduces: TrendChange[];
  newExits: TrendChange[];
  transitions: TrendTransition[];
  movers: TrendChange[];
}

export interface TrendRankingResponse extends TrendSummary {
  items: TrendRankingSnapshot[];
  candidates: TrendCandidate[];
  portfolio: TrendPortfolioResponse;
  changes?: TrendRankingChanges | null;
}
export interface TrendPortfolioPosition {
  code: string;
  name: string;
  state: Extract<TrendState, 'ENTRY' | 'PYRAMIDING' | 'HOLDING' | 'WEAKENING' | 'REDUCE'>;
  action: TrendAction;
  pendingAction: TrendSnapshot['pendingAction'];
  units: number;
  unitWeight: number;
  positionWeight: number;
  maxWeight: number;
  entryPrice: number | null;
  referencePrice: number;
  openedAt: string | null;
  initialStop: number | null;
  trailingStop: number | null;
  nextAddPrice: number | null;
  exitLevel: number | null;
  alphaScore: number;
}
export interface TrendPortfolioResponse {
  market: TrendMarket;
  tradeDate: string;
  marketRegime: TrendRegime;
  maxExposure: number;
  currentExposure: number;
  remainingExposure: number;
  positionCount: number;
  positions: TrendPortfolioPosition[];
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
