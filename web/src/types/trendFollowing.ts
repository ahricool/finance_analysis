export type TrendMarket = 'CN' | 'US';
export type TrendRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
export type TrendState = 'IDLE' | 'WATCHING' | 'CANDIDATE' | 'TRENDING' | 'WEAKENING' | 'BROKEN';

export interface TrendRiskSizing {
  riskBudgetPct: number;
  maxPositionPct: number;
  atrMultiple: number;
  atrStopPct: number;
  structureStopPct: number;
  stopLossPct: number;
  stopPrice: number;
  suggestedPositionPct: number;
  stopBasis: 'ATR' | 'STRUCTURE';
}

export type BoxState = 'NONE' | 'BOX_FORMING' | 'BOX_READY' | 'BOX_BREAKOUT';
export interface BoxFeatures {
  boxBreakoutFresh?: boolean | null;
  boxPriorBreakoutConfirmed?: boolean | null;
  boxEpisodeConsumed?: boolean | null;
  boxEpisodeBreakoutDate?: string | null;
  boxState?: BoxState | null;
  boxStartDate?: string | null;
  boxEndDate?: string | null;
  boxQuality?: number | null;
  boxWindowDays?: number | null;
  boxHigh?: number | null;
  boxLow?: number | null;
  boxMid?: number | null;
  boxWidthPct?: number | null;
  boxSlope?: number | null;
  boxSlopeAtr?: number | null;
  boxRSquared?: number | null;
  boxOccupancy?: number | null;
  boxUpperTouches?: number | null;
  boxLowerTouches?: number | null;
  distanceToBoxHighPct?: number | null;
  distanceToBoxHighAtr?: number | null;
  boxBreakoutDistanceAtr?: number | null;
  boxAtr20?: number | null;
  boxWidthQuality?: number | null;
  boxFlatnessQuality?: number | null;
  boxOccupancyQuality?: number | null;
  boxCompressionQuality?: number | null;
  boxTouchQuality?: number | null;
}

export interface MeanReversionFeatures {
  mrState?: 'MR_NONE' | 'MR_OVERSOLD' | 'MR_REBOUND' | null;
  mrEpisodeConsumed?: boolean | null;
  rsi14?: number | null;
  distanceFromMa20Atr?: number | null;
  return3D?: number | null;
  mrQuality?: number | null;
  mrOversoldQuality?: number | null;
  mrDistanceQuality?: number | null;
  mrShockQuality?: number | null;
  mrReversalQuality?: number | null;
  mrPreviousRsi14?: number | null;
}
export interface TrendFeatures extends BoxFeatures, MeanReversionFeatures {
  riskSizing?: TrendRiskSizing | null;
  previousLow10?: number | null;
  entryBreakdown?: { breakout: EntryBranchBreakdown; resume: EntryBranchBreakdown } | null;
  alphaVersion?: number | null;
  pathScore?: number | null;
  setupScore?: number | null;
  positiveReturnConcentration?: number | null;
  atrExpansionRatio?: number | null;
  downsideControlQuality?: number | null;
  downsideUpsideRatio?: number | null;
  atrPercent?: number | null;
  closeLocationValue?: number | null;
  rawVolumeRatio?: number | null;
  projectedVolumeRatio?: number | null;
  volumeProvisional?: boolean | null;
  pullbackDetected?: boolean | null;
  ma10Reclaimed?: boolean | null;
  trendAcceleration?: number | null;
  signedEfficiencyRatio10D?: number | null;
  r2Quality?: number | null;
  momentumQuality?: number | null;
  return10DQuality?: number | null;
  return20DQuality?: number | null;
  drawdownQuality?: number | null;
  rs5DQuality?: number | null;
  rs10DQuality?: number | null;
  rs20DQuality?: number | null;
  breakoutQuality?: number | null;
  extensionQuality?: number | null;
  volumeQuality?: number | null;
  compressionQuality?: number | null;
  concentrationQuality?: number | null;
  volatilityQuality?: number | null;
  alphaTrendContribution?: number | null;
  alphaRsContribution?: number | null;
  alphaSetupContribution?: number | null;
  alphaPathContribution?: number | null;
  ma10: number;
  ma20: number;
  ma10Slope: number;
  ma20Slope: number;
  trendCandidate: boolean;
  rawWeightedSlope: number;
  weightedSlopePercentile: number;
  weightedR2?: number | null;
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

export interface EntryBranchBreakdown {
  components: Record<string, number | null>;
  normalizedWeights: Record<string, number>;
  contributions: Record<string, number>;
  checks: Record<string, boolean>;
  qualityScore: number;
  score: number;
}

export interface TrendAlphaBreakdown {
  version: number;
  components: Record<string, number>;
  weights: Record<string, number>;
  contributions: Record<string, number>;
  score: number;
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
  entryScore?: number | null;
  entryType?: string | null;
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

export const RANKING_FEATURE_KEYS = [
  'boxBreakoutFresh', 'boxPriorBreakoutConfirmed', 'boxEpisodeConsumed', 'mrEpisodeConsumed', 'rsi14', 'distanceFromMa20Atr', 'return3D',
  'mrQuality', 'mrOversoldQuality', 'mrDistanceQuality', 'mrShockQuality', 'mrReversalQuality', 'mrPreviousRsi14',
  'boxQuality', 'boxWindowDays', 'boxHigh', 'boxLow', 'boxMid', 'boxWidthPct', 'boxSlope', 'boxSlopeAtr', 'boxRSquared', 'boxOccupancy', 'boxUpperTouches', 'boxLowerTouches', 'distanceToBoxHighPct', 'distanceToBoxHighAtr', 'boxBreakoutDistanceAtr', 'boxAtr20', 'boxWidthQuality', 'boxFlatnessQuality', 'boxOccupancyQuality', 'boxCompressionQuality', 'boxTouchQuality',
  'alphaVersion', 'pathScore', 'setupScore', 'weightedR2', 'positiveReturnConcentration',
  'atrExpansionRatio', 'downsideControlQuality', 'downsideUpsideRatio',
  'rawWeightedSlope', 'weightedSlopePercentile', 'return5D', 'return10D', 'return20D',
  'drawdown20D', 'rs5D', 'rs10D', 'rs20D', 'ma10', 'ma20', 'ma10Slope', 'ma20Slope',
  'distanceFromMa20', 'volumeRatio', 'trendAcceleration',
  'atrPercent', 'closeLocationValue', 'rawVolumeRatio', 'projectedVolumeRatio',
  'volumeProvisional', 'pullbackDetected', 'ma10Reclaimed',
  'signedEfficiencyRatio10D', 'trendCandidate', 'priorCompression', 'compressionBreakout',
  'trendResume', 'r2Quality', 'momentumQuality', 'return10DQuality', 'return20DQuality',
  'drawdownQuality', 'rs5DQuality', 'rs10DQuality', 'rs20DQuality',
  'breakoutQuality', 'extensionQuality', 'volumeQuality', 'compressionQuality',
  'concentrationQuality', 'volatilityQuality',
  'alphaTrendContribution', 'alphaRsContribution', 'alphaSetupContribution', 'alphaPathContribution',
] as const;
export type RankingFeatureKey = typeof RANKING_FEATURE_KEYS[number];
export type TrendRankingFeatures = Partial<Record<RankingFeatureKey, number | boolean | null>> & BoxFeatures & MeanReversionFeatures;

export interface TrendRankingSnapshot extends Pick<TrendSnapshot,
  'code' | 'name' | 'rank' | 'trendDurationDays' | 'trendLifecycle' | 'fragilityScore' | 'alphaScore' | 'entryScore' | 'entryType'> {
  state: TrendState | null;
  trendScore: number | null;
  rsScore: number | null;
  breakoutScore: number | null;
  setup: string | null;
  atr: number | null;
  referencePrice: number | null;
  features: TrendRankingFeatures;
  scoreBreakdown?: Record<string, unknown>;
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


export interface TrendBreadthPoint {
  stateCounts: Record<TrendState, number>;
  tradeDate: string;
  rankableCount: number | null;
  trendBreadth: number | null;
  deteriorationBreadth: number | null;
  participation: number | null;
  inactive: number | null;
  emerging: number | null;
  healthy: number | null;
  deteriorating: number | null;
  coverage: number | null;
  warning: string | null;
  isPreview: boolean;
}
export interface TrendBreadthResponse {
  market: TrendMarket;
  dates: string[];
  officialCount: number;
  previewDate: string | null;
  previewTime: string | null;
  generatedAt: string | null;
  points: TrendBreadthPoint[];
  warnings: string[];
}
export type TransitionDirection = 'all' | 'strengthening' | 'deteriorating';
export interface RecentTrendTransition {
  code: string;
  name: string;
  previousState: TrendState;
  currentState: TrendState;
  previousDate: string;
  tradeDate: string;
  previousRank: number;
  currentRank: number;
  rankDelta: number;
  alphaScore: number | null;
  fragilityScore: number | null;
  direction: Exclude<TransitionDirection, 'all'>;
  priority: number;
  isPreview: boolean;
}
export interface TrendTransitionsResponse {
  market: TrendMarket;
  days: number;
  officialCount: number;
  previewDate: string | null;
  warnings: string[];
  items: RecentTrendTransition[];
}

/** Bounded homepage payload; counts include every qualifying transition. */
export interface TrendDashboardResponse extends Pick<TrendSummary,
  'market' | 'tradeDate' | 'marketRegime' | 'marketScore'> {
  scoreBreakdown: Record<string, number | null>;
  features: { lifecycleCounts: Record<string, number> | null; highFragilityCount: number | null };
  changes: {
    previousTradeDate: string | null;
    stateCounts: Record<string, number>;
    highlights: Array<{ code: string; name: string | null; previousState: TrendState; currentState: TrendState }>;
  };
}

export type StrategyKey = 'TREND_FOLLOWING' | 'BOX_BREAKOUT' | 'PULLBACK_RESUME' | 'MEAN_REVERSION';
export type StudyRegime = 'ALL' | TrendRegime;
export type EvaluationStatus = 'pending' | 'missing' | 'available';
export interface StudyCoverage {
  featureCoverage: number | null;
  featureSnapshotCount: number;
  snapshotCount: number;
  status: 'complete' | 'insufficient_feature_history';
  continuousCompleteSince: string | null;
  incompleteDates: string[];
}
export interface StudyHorizonAggregate {
  days: number; maturedCount: number; excessMaturedCount: number; pendingCount: number; missingCount: number;
  meanReturn: number | null; medianReturn: number | null; winRate: number | null;
  meanExcessReturn: number | null; medianExcessReturn: number | null; excessWinRate: number | null;
}
export interface StudyGroup extends StudyCoverage {
  strategy: StrategyKey; regime: StudyRegime; eventCount: number;
  horizons: StudyHorizonAggregate[]; excursionCount: number;
  mfe20: { mean: number | null; median: number | null };
  mae20: { mean: number | null; median: number | null };
}
export interface StudyHorizon {
  days: number; targetDate: string; status: EvaluationStatus; value: number | null;
  benchmarkStatus: EvaluationStatus; benchmarkReturn: number | null;
  excessStatus: EvaluationStatus; excessReturn: number | null;
}
export interface StudyEvent {
  market: TrendMarket; tradeDate: string; code: string; name: string | null; strategy: StrategyKey; regime: TrendRegime;
  signalPrice: number; evaluationBasePrice: number | null; context: Record<string, string | number | null>;
  horizons: StudyHorizon[]; excursionStatus: EvaluationStatus; observedSessions: number; missingDates: string[];
  mfe20: number | null; mae20: number | null;
}
export interface EventStudyResponse {
  market: TrendMarket; startDate: string; endDate: string; method: 'signal_close_v1'; benchmark: string;
  evaluatedAt: string; snapshotDates: string[]; missingSnapshotDates: string[];
  boxFeatureCoverage: StudyCoverage; mrFeatureCoverage: StudyCoverage;
  groups: StudyGroup[]; eventCount: number; events: StudyEvent[]; offset: number; limit: number;
}
