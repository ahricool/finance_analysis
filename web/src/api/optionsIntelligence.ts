import apiClient from './index';
import { toCamelCase } from './utils';

export interface OptionScore {
  value: number | null; method: string; evidenceCount: number; confidence: string; reason: string | null;
}
export interface OptionScores { bearishDemand: OptionScore; unusualActivity: OptionScore; liquidityRisk: OptionScore }
export interface OptionTerm {
  expiration: string; dte: number; atmIv: number | null; skew25: number | null;
  expectedMove: number | null; expectedMoveMethod: string; source: string; feedType: string;
}
export interface OptionSkew { targetDte: number; actualDte: number | null; expiration: string | null;
  value: number | null; source: string | null; feedType: string | null; reason: string | null }
export interface OptionEvidence {
  contractSymbol: string; eventType: string; value: number; severity: number; evidenceGrade: string;
  source: string; feedType: string; dataTime: string; direction: string; explanation: string;
  confidence: string; reference: Record<string, unknown>;
}
export interface OptionContract {
  symbol: string; expiration: string; optionType: string; strike: number; multiplier: number | null;
  bid: number | null; ask: number | null; bidSize: number | null; askSize: number | null;
  volume: number | null; volumeDate?: string | null; openInterest: number | null; oiDate: string | null;
  iv: number | null; delta: number | null; gamma: number | null; theta: number | null; vega: number | null;
  spread: number | null; volumeOi: number | null; quoteStatus: string; quoteTimestamp: string | null;
  dataSource: string; feedType: string; observedAt: string; notes: string[]; limitations: string[];
  risk: OptionScore; volumePercentile: number | null; baselineDays: number;
  premiumEstimate: number | null; premiumVolume: number | null; events: string[];
}
export interface OptionExplanation {
  whyItMatters: string; possibleCatalysts: string[]; protectionVsDirection: string;
  alternativeExplanations: string[]; dataLimits: string[]; tradingRisks: string[];
}
export interface OptionMetrics {
  symbol: string; status: string; tradeDate?: string; observedAt?: string; computedAt?: string;
  underlyingPrice?: number | null; scores: OptionScores | null; evidenceGrade?: string; confidence?: string;
  historyDays?: number; iv30D?: number | null; iv30DMethod?: string; ivPercentile?: number | null; ivSampleCount?: number;
  ivSource?: string[]; rv20D?: number | null; ivRvRatio?: number | null; skew30D?: number | null; skewChange?: number | null;
  putCallVolumeRatio?: number | null; volumeSource?: string | null;
  putCallRatios?: Array<{ dteMin: number; dteMax: number; volumeRatio: number | null; oiRatio: number | null; source: string }>;
  termStructure?: OptionTerm[]; skewTerms?: OptionSkew[]; contracts?: OptionContract[]; events?: OptionEvidence[];
  limitations: string[]; riskSummary?: string; topEvent?: OptionEvidence | null; eventTypes?: string[];
  llmAnalysis?: OptionExplanation | null; coverage?: Record<string, unknown>;
}
export interface OptionEvent {
  id: number; symbol: string; eventType: string; contractSymbol: string; tradeDate: string;
  occurredAt: string; updatedAt: string; dataSource: string; feedType: string;
  initialEvidence: OptionEvidence; latestEvidence: OptionEvidence;
  validation: { oiConfirmation?: { change: number; oiDate: string; previousOiDate: string; knownAt: string } };
  evaluation: { status: string; entryDate?: string; entryPrice?: number | null; maxAdverse5D?: number | null;
    subsequentRv20D?: number | null; rvChange?: number | null;
    returns?: Array<{ days: number; value: number | null; status: string }>;
    benchmarks?: Record<string, Array<{ days: number; value: number | null }>> };
}
export interface OptionsDetail {
  symbol: string; latest: OptionMetrics | null; dailyHistory: OptionMetrics[]; events: OptionEvent[];
  analyses: Array<{ createdAt: string; explanation: OptionExplanation; model: string | null }>; reason: string | null;
}
const base = '/api/v1/options-intelligence';
export const optionsIntelligenceApi = {
  async scan(): Promise<{ items: OptionMetrics[] }> {
    return toCamelCase((await apiClient.get(base)).data);
  },
  async detail(symbol: string): Promise<OptionsDetail> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(symbol)}`)).data);
  },
  async refresh(symbol: string, explain = false): Promise<{ taskId: string; status: string }> {
    return toCamelCase((await apiClient.post(`${base}/${encodeURIComponent(symbol)}/${explain ? 'explain' : 'refresh'}`)).data);
  },
  async run(): Promise<{ taskId: string }> { return toCamelCase((await apiClient.post(`${base}/run`, {})).data); },
};
