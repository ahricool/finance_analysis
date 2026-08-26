export type ETFState = 'EMERGING' | 'TRENDING' | 'STRONG' | 'COOLING' | 'EXHAUSTED' | 'WEAK' | 'NEUTRAL';

export interface ETFUniverseMember {
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
  ret1d: number;
  ret5d: number;
  ret10d: number;
  ret20d: number;
  ret30d: number;
  ret60d: number;
  rank1d: number;
  rank5d: number;
  rank10d: number;
  rank20d: number;
  rank30d: number;
  rank60d: number;
  pctRank1d: number;
  pctRank5d: number;
  pctRank10d: number;
  pctRank20d: number;
  pctRank30d: number;
  pctRank60d: number;
  previous5dReturn: number;
  momentumAcceleration: number;
  rankChange1d: number | null;
  rankChange3d: number | null;
  rankChange5d: number | null;
  ma20Ratio: number;
  ma60Ratio: number;
  volumeRatio5d: number | null;
  avgAmount20d: number | null;
  realizedVol20d: number;
  distanceFrom20dHigh: number;
  momentumScore: number;
  entryScore: number;
  state: ETFState;
  overheated: boolean;
  candidateRank: number | null;
  isCandidate: boolean;
  scoreComponents: Record<string, number>;
  generatedAt: string;
}

export interface ETFRankingResponse {
  tradeDate: string;
  universeSize: number;
  dataReadyCount: number;
  dataCoverage: number;
  rankableSize: number;
  rankableCoverage: number;
  generatedAt: string | null;
  warnings: string[];
  items: ETFMomentumSnapshot[];
}

export interface ETFCandidatesResponse { tradeDate: string; items: ETFMomentumSnapshot[] }
export interface ETFDatesResponse { latest: string | null; items: string[] }
export interface ETFDetailResponse {
  metadata: ETFUniverseMember;
  latest: ETFMomentumSnapshot;
  history: ETFMomentumSnapshot[];
}
export interface ETFRotationRunAccepted {
  taskId: string;
  status: 'pending';
  market: 'CN';
  tradeDate: string | null;
}
