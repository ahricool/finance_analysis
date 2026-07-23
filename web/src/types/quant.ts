export type CapabilityState = 'available' | 'configured' | 'unavailable' | 'degraded' | 'data_dependent';
export type QuantMarket = 'US' | 'CN';

export interface QuantCapabilities {
  status: CapabilityState;
  market: QuantMarket;
  pythonVersion: string;
  priceModes: string[];
  markets: Record<string, CapabilityState>;
  qlib: { status: CapabilityState; version: string; execution: string; reason: string | null };
  models: { status: CapabilityState; required: Record<string, 'production' | 'unavailable'> };
  adjustedPrices: { status: CapabilityState; reason: string };
  warnings: string[];
}

export interface QuantUniverse { id: number; key: string; name: string; market: string; benchmarkCode: string | null; config: Record<string, unknown>; memberCount: number }
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
  priceMode: string;
  featureVersion: string;
  artifactUri: string | null;
  rowCount: number;
  symbolCount: number;
  status: 'pending' | 'building' | 'ready' | 'failed';
  validationResult: Record<string, unknown>;
  createdAt: string;
  finishedAt: string | null;
}
export interface DatasetBuildAccepted { taskId: string; status: string; market: QuantMarket; universe: string }
export interface ModelRunCreateAccepted { modelRunId: number; taskId: string; status: string; market: QuantMarket }
export interface ModelRunCreatePayload {
  market: QuantMarket;
  modelKey: 'cross_section_lgbm' | 'time_series_lgbm';
  modelVersion: string;
  datasetSnapshotId: number;
}
export interface MarketRegime { id: number; tradeDate: string; market: string; modelVersion: string; regime: 'risk_on'|'neutral'|'risk_off'; marketScore: number; maxEquityExposure: number; features: Record<string, number|null>; reasons: string[] }
export interface SectorRegime { market: QuantMarket; tradeDate: string; sectorKey: string; benchmarkCode: string; sectorScore: number; rank: number; state: string; features: Record<string, number|null> }
export interface QuantSignal { id: number; tradeDate: string; market: QuantMarket; code: string; finalScore: number; rawFinalScore: number; gatedFinalScore: number; marketScore: number|null; sectorScore: number|null; timeSeriesScore: number|null; crossSectionScore: number|null; riskPenalty: number; universeRank: number|null; sectorRank: number|null; predictedReturn: number|null; signal: string; targetPosition: number; vetoed: boolean; vetoReason: string|null; reasons: string[]; scoreComponents: Record<string, number|null> }
export interface SignalRanking { tradeDate: string|null; market: QuantMarket; universe: string; marketRegime: string|null; maxEquityExposure: number|null; items: QuantSignal[] }
export interface ModelRun { id:number; modelKey:string; modelVersion:string; runType:string; market:string; status:string; progress:number; trainStart:string|null; trainEnd:string|null; validStart:string|null; validEnd:string|null; testStart:string|null; testEnd:string|null; metrics:Record<string,number|null>; warnings:string[]; error:string|null; artifactUri:string|null; createdAt:string }
export interface PortfolioItem { id:number; code:string; sectorKey:string|null; rank:number; previousRank:number|null; action:string; currentWeight:number; targetWeight:number; weightChange:number; finalScore:number; predictedReturn:number|null; reasons:string[]; constraints:Record<string,unknown> }
export interface Portfolio { id:number; tradeDate:string; market:string; modelVersion:string; status:string; maxEquityExposure:number; targetEquityExposure:number; summary:Record<string,unknown>; warnings:string[]; generatedAt:string; items:PortfolioItem[] }
export interface IntradayConfirmation { id:number; tradeDate:string; code:string; evaluatedAt:string; decision:'confirm'|'wait'|'reject'|'expired'|'insufficient_data'; confidence:number; price:number|null; vwap:number|null; priceVsVwap:number|null; vwapSlope:number|null; first30mReturn:number|null; volumeRatio:number|null; relativeStrengthMarket:number|null; relativeStrengthSector:number|null; reasons:string[] }
