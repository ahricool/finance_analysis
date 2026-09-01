export type ETFState = 'EMERGING' | 'TRENDING' | 'STRONG' | 'COOLING' | 'EXHAUSTED' | 'WEAK' | 'NEUTRAL';
export type ETFMarket = 'CN' | 'US';
export type ETFAction = 'BUY' | 'HOLD' | 'EXIT' | 'WATCH';
export type MarketRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';

export interface ETFMarketRotationSnapshot {
  tradeDate: string;
  market: ETFMarket;
  regime: MarketRegime;
  positive5dBreadth: number | null;
  aboveMa10Breadth: number | null;
  benchmarkCode: string;
  benchmarkClose: number;
  benchmarkRet5D: number | null;
  benchmarkMa10Ratio: number | null;
  benchmarkWeightedSlope10D: number | null;
  benchmarkTrend: 'POSITIVE' | 'MIXED' | 'NEGATIVE';
}

export interface ETFUniverseMember {
  market: ETFMarket;
  code: string;
  name: string;
  category: string;
  theme: string;
  riskGroup: string;
  enabled: boolean;
}

export interface ETFMomentumSnapshot extends ETFUniverseMember {
  id: number;
  tradeDate: string;
  // camelcase-keys treats digit→letter as a word break, so ret_5d becomes ret5D (not ret5d).
  ret1D: number;
  ret3D: number | null;
  ret5D: number;
  ret10D: number;
  ret20D: number;
  rank1D: number;
  rank3D: number | null;
  rank5D: number;
  rank10D: number;
  rank20D: number;
  pctRank1D: number;
  pctRank3D: number | null;
  pctRank5D: number;
  pctRank10D: number;
  pctRank20D: number;
  previous3dReturn: number | null;
  previous5dReturn: number;
  momentumAcceleration3D: number | null;
  momentumAcceleration5D: number | null;
  rankChange1D: number | null;
  rankChange3D: number | null;
  rankChange5D: number | null;
  ma10Ratio: number | null;
  ma20Ratio: number;
  volumeRatio5D: number | null;
  avgAmount20D: number | null;
  realizedVol20D: number;
  referencePrice: number | null;
  stopLossPct: number | null;
  suggestedStopPrice: number | null;
  distanceFrom20dHigh: number;
  weightedSlope5D: number | null;
  weightedSlope10D: number | null;
  weightedSlope15D: number | null;
  annualizedSlope5D: number | null;
  annualizedSlope10D: number | null;
  annualizedSlope15D: number | null;
  trendR215D: number | null;
  trendQuality15D: number | null;
  signedEfficiencyRatio10D: number | null;
  trendAcceleration: number | null;
  rs5D: number | null;
  rs10D: number | null;
  rs20D: number | null;
  relativeStrengthReady: boolean | null;
  maxDrawdown20D: number | null;
  momentumScore: number;
  momentumStrengthScore: number | null;
  trendQualityScore: number | null;
  relativeStrengthScore: number | null;
  accelerationScore: number | null;
  efficiencyScore: number | null;
  compositeScore: number | null;
  rank: number | null;
  entryScore: number;
  absoluteTrendEligible: boolean | null;
  liquidityEligible: boolean | null;
  action: ETFAction | null;
  state: ETFState;
  overheated: boolean;
  candidateRank: number | null;
  isCandidate: boolean;
  scoreComponents: Record<string, number>;
  diagnostics: Record<string, unknown>;
  generatedAt: string;
}

export interface ETFRankingResponse {
  market: ETFMarket;
  tradeDate: string;
  universeSize: number;
  dataReadyCount: number;
  dataCoverage: number;
  rankableSize: number;
  rankableCoverage: number;
  generatedAt: string | null;
  warnings: string[];
  marketSnapshot: ETFMarketRotationSnapshot | null;
  items: ETFMomentumSnapshot[];
  changes?: ETFRankingChanges | null;
}

export interface ETFChange {
  current: ETFMomentumSnapshot;
  previousState: ETFState | null;
  previousAction: ETFAction | null;
  previousRank: number | null;
  rankChange: number | null;
  compositeScoreChange: number | null;
}

export interface ETFRegimeChange {
  from: MarketRegime;
  to: MarketRegime;
}

export interface ETFRankingChanges {
  previousTradeDate: string | null;
  newBuys: ETFChange[];
  newExits: ETFChange[];
  newEmerging: ETFChange[];
  newCooling: ETFChange[];
  regimeChange: ETFRegimeChange | null;
  rankMovers: ETFChange[];
}

export interface ETFCandidatesResponse {
  market: ETFMarket;
  tradeDate: string;
  marketSnapshot: ETFMarketRotationSnapshot | null;
  items: ETFMomentumSnapshot[];
  candidates?: ETFMomentumSnapshot[];
  exits?: ETFMomentumSnapshot[];
}
export interface ETFDatesResponse { market: ETFMarket; latest: string | null; items: string[] }
export interface ETFDetailResponse {
  market: ETFMarket;
  metadata: ETFUniverseMember;
  latest: ETFMomentumSnapshot;
  history: ETFMomentumSnapshot[];
  marketSnapshot: ETFMarketRotationSnapshot | null;
}
export interface ETFRotationRunAccepted {
  taskId: string;
  status: 'pending';
  market: ETFMarket;
  tradeDate: string | null;
}

export interface ETFUniverseResponse {
  market: ETFMarket;
  size: number;
  items: ETFUniverseMember[];
}
