import apiClient from './index';
import { toCamelCase } from './utils';

export type TrendDirection = 'bullish' | 'bearish' | 'neutral' | 'conflict';
export type TrendStage = 'continuing' | 'pullback' | 'extended' | 'conflict' | 'waiting';
export interface WindowScore {
  availableBars?: number | null; missingBars?: number | null;
  minutes: 5 | 15 | 30 | 60; dataStatus: 'ready' | 'warming' | 'gap'; score: number | null;
  direction: -1 | 0 | 1 | null; returnPct: number | null; startAt: string | null; endAt: string | null;
  stability: number | null; efficiency: number | null; strength: number | null; disturbance: number | null;
  normalizedMove: number | null; adverseMove: number | null; adverseDuration: number | null;
  movementGate: number | null; concentration: number | null; stalledImpulse: boolean; reasons: string[];
}
export interface AnalysisCoverage {
  requiredMinutes?: number; recentAvailableBars?: number; recentMissingBars?: number;
  filledBars?: number; filledMinutes?: string[];
}
export interface IntradayStructure extends AnalysisCoverage {
  kind: 'uptrend' | 'downtrend' | 'range' | 'breakout_up' | 'breakout_down' | 'failed_up' | 'failed_down' | 'rebound' | 'pullback' | 'unclear';
  phase: 'waiting' | 'forming' | 'confirmed' | 'retest' | 'failed' | 'continuing' | 'pullback' | 'pausing' | 'inside' | 'warming';
  background: 'bullish' | 'bearish' | 'neutral'; since: string; confirmedAt?: string | null; asOf: string;
  oversold: boolean; reference: boolean; availableBars: number; missingBars: number;
  box: { upper: number; lower: number; startAt: string; endAt: string; atr: number } | null;
  pivots: Array<{ kind: 'high' | 'low'; at: string; confirmedAt: string; price: number }>;
  reasons: string[];
}
export interface OpportunityBranch {
  kind: 'box_breakout' | 'box_retest' | 'trend_recovery' | 'trend_continuation' | 'opening_breakout' | 'pivot_breakout';
  confirmationMethod?: 'two_closes' | 'strong_break' | 'level_close' | null;
  confirmationAvailableAt?: string | null; confirmationRunAvailableAt?: string | null; executionEvidenceAt?: string | null;
  triggeredAt?: string | null; structureStart?: string | null; structureEnd?: string | null;
  structureHigh?: number | null; structureLow?: number | null;
  atrSource?: string | null; atrSamples?: number | null; ruleVersion?: string | null;
  supersededBy?: string | null; breakoutRejection?: string | null;
  direction: 'bullish' | 'bearish'; status: 'forming' | 'confirmed' | 'extended' | 'invalidated' | 'expired';
  structureId: string; trigger: number; invalidation: number; atr: number;
  formationStart: string; startedAt: string; confirmedAt: string | null; expiresAt: string;
  qualityScore: number | null; distanceAtr: number | null; riskAtr: number | null;
  components: Record<string, number>; reasons: string[];
}
export interface IntradayOpportunities extends AnalysisCoverage {
  version: string; primary: OpportunityBranch | null; branches: OpportunityBranch[];
  reference: boolean; missingBars: number; asOf: string; reasons: string[];
}
export interface TrendResult {
  opportunities?: IntradayOpportunities | null;
  structure?: IntradayStructure | null;
  version: string; symbol: string; tradingDate: string; asOf: string; observedAt: string;
  windows: WindowScore[]; score: number | null; direction: TrendDirection | null; state: TrendStage | null;
  baseScore: number | null; alignment: number | null; extensionAtr: number | null; explanation: string;
}
export interface IntradayOptionRow {
  simulation?: SimulationState | null;
  rankedOpportunity?: (OpportunityBranch & { opportunityReason: string; executionReason: string }) | null;
  opportunityEligible?: boolean;
  symbol: string; name: string | null; lastPrice: number | null; changePct: number | null; quoteTime: string | null;
  quoteStatus: 'missing' | 'ready' | 'delayed' | 'invalid_time';
  dataStatus: 'ready' | 'waiting' | 'warming' | 'gap' | 'delayed' | 'invalid_time';
  issues: string[]; result: TrendResult | null;
}
export interface IntradayOptionsSnapshot {
  simulation?: SimulationSnapshot | null;
  tradingDate: string; marketStatus: 'open' | 'preopen' | 'closed'; generatedAt: string;
  version: string; items: IntradayOptionRow[];
}
export async function fetchIntradayOptions(signal: AbortSignal): Promise<IntradayOptionsSnapshot> {
  const { data } = await apiClient.get('/api/v1/intraday-options', { signal });
  return toCamelCase<IntradayOptionsSnapshot>(data);
}

export interface SimulationPlan extends OpportunityBranch {
  entryQuoteNotBefore?: string | null;
  processId: string; entryLow: number; entryHigh: number; target: number | null; targetSource: string;
  remainingReturn?: number | null; initialRisk?: number | null;
  remainingSpace: number | null; rewardRisk: number | null; ageSeconds: number | null;
  opportunityValid?: boolean; opportunityReason?: string; executable: boolean; executionReason: string;
}
export interface SimTrade {
  confirmationMethod?: OpportunityBranch['confirmationMethod'];
  entryEvidence?: Partial<SimulationPlan>;
  entryPriceAt?: string; tradingDate?: string;
  opportunityId?: string; id: string; symbol: string; side: number; kind: OpportunityBranch['kind']; entryPrice: number; entryAt: string;
  lastPrice: number; lastPriceAt: string; invalidation: number; protection: number; target: number | null;
  returnPct: number; exitAt?: string; exitPrice?: number; exitPriceAt?: string; plannedExitAt?: string;
  exitReason?: string; estimated?: boolean; anomaly?: string;
}
export interface SimulationState {
  sessionPhase?: 'active' | 'preopen' | 'stopped' | 'closed'; sessionOpen?: string | null; dataIssue?: string | null;
  symbol: string; calculatedAt: string; cutoff: string | null; stopped: boolean; currentPrice: number | null;
  quoteTime: string | null; position?: SimTrade | null; plans: SimulationPlan[];
  relativeStrength?: Array<{ minutes: number; value: number | null; start: string; end: string; reason: string }>;
}
export interface SimulationSnapshot {
  references?: { background: { label: string; asOf: string | null; reason: string }; macroStatus: string;
    macro: Array<{ title: string; at: string; asOf: string; reason: string }> };
  states: SimulationState[]; trades: SimTrade[];
  events: Array<{ id: number; kind: string; symbol: string; at: string; reason: string; side?: number; tradeId?: string; trade?: SimTrade }>;
  statistics: Array<{ label: string; count: number; winRate: number | null; averageReturn: number | null;
    averageWin: number | null; averageLoss: number | null; averageDuration: number | null }>;
}
