export type CapabilityState = 'available' | 'configured' | 'unavailable' | 'degraded' | 'data_dependent';
export type QuantMarket = 'US' | 'CN';

export interface QuantCapabilities {
  status: CapabilityState;
  market: QuantMarket;
  pythonVersion: string;
  dailyPriceSemantics: 'forward_adjusted';
  markets: Record<string, CapabilityState>;
  qlib: { status: CapabilityState; version: string; execution: string; reason: string | null };
  models: { status: CapabilityState; required: Record<string, 'production' | 'unavailable'> };
  warnings: string[];
}

export interface QuantUniverseMember {
  code: string;
  name: string | null;
  sectorKey: string | null;
  sectorBenchmarkCode: string | null;
  effectiveFrom: string | null;
  effectiveTo: string | null;
}
export interface QuantUniverse {
  id: number;
  key: string;
  name: string;
  market: QuantMarket;
  benchmarkCode: string | null;
  config: Record<string, unknown>;
  memberCount: number;
  members: QuantUniverseMember[];
}
export interface QuantModelDefinition {
  id: number;
  key: string;
  name: string;
  modelType: string;
  taskType: string;
  frequency: string;
  enabled: boolean;
  supportedMarkets: QuantMarket[];
}
export interface QuantDatasetSnapshot {
  id: number;
  datasetKey: string;
  market: QuantMarket;
  dateFrom: string;
  dateTo: string;
  featureVersion: string;
  artifactUri: string | null;
  rowCount: number;
  symbolCount: number;
  universeMemberCount: number;
  universeCoverageRatio: number;
  minimumUniverseCoverage: number;
  trainable: boolean;
  status: 'pending' | 'building' | 'ready' | 'failed';
  validationResult: Record<string, unknown>;
  createdAt: string;
  finishedAt: string | null;
}
export interface DatasetBuildAccepted { taskId: string; status: string; market: QuantMarket; universe: string }
export interface ModelRunCreateAccepted { modelRunId: number; taskId: string; status: 'pending'; market: QuantMarket }
export interface QuantDeleteResult { id: number; deleted: boolean; artifactDeleted: boolean }
export interface ModelRunCreatePayload {
  market: QuantMarket;
  modelKey: 'cross_section_lgbm' | 'time_series_lgbm';
  modelVersion: string;
  datasetSnapshotId: number;
}
export interface MarketScoreComponent {
  key: string;
  label: string;
  group: string;
  groupLabel: string;
  rawValue: number;
  rawFormat: 'percent' | 'number';
  score: number;
  weight: number;
  contribution: number;
}
export interface MarketScoreGroup {
  key: string;
  label: string;
  weight: number;
  score: number;
  contribution: number;
  components: MarketScoreComponent[];
}
export interface MarketScoreBreakdown {
  version: string;
  score: number;
  weightTotal: number;
  groups: MarketScoreGroup[];
}
export interface MarketRegime {
  id: number;
  tradeDate: string;
  market: string;
  modelVersion: string;
  regime: 'risk_on'|'neutral'|'risk_off';
  marketScore: number;
  maxEquityExposure: number;
  features: Record<string, unknown>;
  reasons: string[];
  scoreBreakdown: MarketScoreBreakdown | null;
}
export interface SectorRegime { market: QuantMarket; tradeDate: string; sectorKey: string; benchmarkCode: string; benchmarkName: string|null; sectorScore: number; rank: number; state: string; features: Record<string, number|null> }
export interface QuantSignal { id: number; tradeDate: string; market: QuantMarket; code: string; name:string|null; modelVersion: string; finalScore: number; rawFinalScore: number; gatedFinalScore: number; marketScore: number|null; sectorScore: number|null; timeSeriesScore: number|null; crossSectionScore: number|null; riskPenalty: number; universeRank: number|null; sectorRank: number|null; predictedReturn: number|null; signal: string; targetPosition: number; vetoed: boolean; vetoReason: string|null; reasons: string[]; scoreComponents: Record<string, number|null> }
export interface SignalRanking { tradeDate: string|null; market: QuantMarket; universe: string; modelVersion: string|null; marketRegime: string|null; maxEquityExposure: number|null; items: QuantSignal[] }
export interface ModelRun { id:number; modelKey:string; modelVersion:string; runType:string; market:string; status:string; progress:number; trainStart:string|null; trainEnd:string|null; validStart:string|null; validEnd:string|null; testStart:string|null; testEnd:string|null; metrics:Record<string,number|null>; warnings:string[]; error:string|null; artifactUri:string|null; createdAt:string }
export interface PortfolioItem { id:number; code:string; name:string|null; sectorKey:string|null; rank:number; previousRank:number|null; action:string; currentWeight:number; targetWeight:number; weightChange:number; finalScore:number; predictedReturn:number|null; reasons:string[]; constraints:Record<string,unknown> }
export interface Portfolio { id:number; tradeDate:string; market:QuantMarket; universe:string; modelVersion:string; status:string; maxEquityExposure:number; targetEquityExposure:number; summary:Record<string,unknown>; warnings:string[]; generatedAt:string; items:PortfolioItem[] }
export interface IntradayConfirmation { id:number; tradeDate:string; code:string; name:string|null; evaluatedAt:string; decision:'confirm'|'wait'|'reject'|'expired'|'insufficient_data'; confidence:number; price:number|null; vwap:number|null; priceVsVwap:number|null; vwapSlope:number|null; first30mReturn:number|null; volumeRatio:number|null; relativeStrengthMarket:number|null; relativeStrengthSector:number|null; reasons:string[] }
