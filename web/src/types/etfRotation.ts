export type ETFState = 'EMERGING' | 'TRENDING' | 'STRONG' | 'COOLING' | 'EXHAUSTED' | 'WEAK' | 'NEUTRAL';
export type ETFMarket = 'CN' | 'US';
export type ETFAction = 'BUY' | 'HOLD' | 'EXIT' | 'WATCH';
export type MarketRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';

export interface ETFMarketRotationSnapshot {
  tradeDate: string;
  market: ETFMarket;
  regime: MarketRegime;
  breadthAboveMa20: number;
  breadthAboveMa60: number;
  breadthMa20AboveMa60: number;
  benchmarkCode: string;
  benchmarkClose: number;
  benchmarkMa20Ratio: number;
  benchmarkMa60Ratio: number;
  benchmarkTrend: 'POSITIVE' | 'MIXED' | 'NEGATIVE';
  benchmarkAboveMa20: boolean;
  benchmarkAboveMa60: boolean;
  benchmarkMa20AboveMa60: boolean;
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
  ret5D: number;
  ret10D: number;
  ret20D: number;
  ret30D: number;
  ret60D: number;
  rank1D: number;
  rank5D: number;
  rank10D: number;
  rank20D: number;
  rank30D: number;
  rank60D: number;
  pctRank1D: number;
  pctRank5D: number;
  pctRank10D: number;
  pctRank20D: number;
  pctRank30D: number;
  pctRank60D: number;
  previous5dReturn: number;
  momentumAcceleration: number;
  rankChange1D: number | null;
  rankChange3D: number | null;
  rankChange5D: number | null;
  ma20Ratio: number;
  ma60Ratio: number;
  volumeRatio5D: number | null;
  avgAmount20D: number | null;
  realizedVol20D: number;
  referencePrice: number | null;
  stopLossPct: number | null;
  suggestedStopPrice: number | null;
  distanceFrom20dHigh: number;
  weightedSlope10D: number | null;
  weightedSlope25D: number | null;
  annualizedSlope10D: number | null;
  annualizedSlope25D: number | null;
  trendR225D: number | null;
  trendQuality25D: number | null;
  efficiencyRatio20D: number | null;
  trendAcceleration: number | null;
  rs20D: number | null;
  rs60D: number | null;
  relativeStrengthReady: boolean | null;
  riskAdjustedMomentum60D: number | null;
  maxDrawdown20D: number | null;
  maxDrawdown60D: number | null;
  momentumScore: number;
  momentumStrengthScore: number | null;
  trendQualityScore: number | null;
  relativeStrengthScore: number | null;
  accelerationScore: number | null;
  efficiencyScore: number | null;
  riskAdjustedScore: number | null;
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
}

export interface ETFCandidatesResponse { market: ETFMarket; tradeDate: string; marketSnapshot: ETFMarketRotationSnapshot | null; items: ETFMomentumSnapshot[] }
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
