import apiClient from './index';
import { toCamelCase } from './utils';

export type ReviewAction = 'HOLD' | 'BUY' | 'REDUCE' | 'SELL' | 'WATCH';
export type ReviewConfidence = 'HIGH' | 'MEDIUM' | 'LOW';
export interface HoldingAdvice {
  positionId: string; symbol: string; action: ReviewAction; changePct: number;
  rationale: string; condition: string; invalidation: string; confidence: ReviewConfidence;
}
export interface FrozenHolding {
  positionId: string; accountId: string; accountName?: string; symbol: string; name: string; quantity: number; averageCost: number;
  currentPrice: number | null; quoteTime: string | null; marketValue: number | null; weightPct: number | null;
  unrealizedPnlPct: number | null; changePct: number | null; dataComplete: boolean; todayBuyQuantity: number;
}
export interface ResearchInput { status: string; observedAt?: string; reason?: string; items: Array<Record<string, unknown>> }
export interface HoldingsReview {
  id: number; market: 'CN' | 'US'; tradeDate: string; status: 'processing' | 'completed' | 'failed';
  asOf: string | null; sessionClose: string | null; startedAt: string; completedAt: string | null;
  decision: {
    marketState: 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF' | 'UNCERTAIN'; conclusion: string; confidence: ReviewConfidence;
    sectors: Array<{ name: string; strength: string; rationale: string }>;
    risks: Array<{ title: string; severity: string; detail: string }>;
    positions: HoldingAdvice[]; watchpoints: string[]; degraded: boolean;
  } | null;
  holdings: FrozenHolding[]; dataQuality: string[]; markdown: string | null; error: string | null; model: string | null;
  portfolio: { cash?: number; nav?: number | null; holdingCount?: number; currency?: string; valuationComplete?: boolean };
  indices: Array<{ symbol: string; name: string; currentPrice: number | null; changePct: number | null; dailyCount: number }>;
  research: { etfRotation?: ResearchInput; holdingTrends?: ResearchInput; industryStrength?: ResearchInput };
  searchEvidence: { status?: string; citations?: Array<{ title: string; url: string }> };
}
export interface ReviewResponse {
  review: HoldingsReview | null; requestedDate: string; today: string; previousTradeDate: string;
  scheduledAt: string; canRun: boolean;
}
export const holdingsReviewApi = {
  async detail(market: string, tradeDate?: string): Promise<ReviewResponse> {
    return toCamelCase((await apiClient.get('/api/v1/holdings-review', {
      params: { market, trade_date: tradeDate },
    })).data);
  },
  async dates(market: string): Promise<Array<{ tradeDate: string; status: string }>> {
    return toCamelCase((await apiClient.get('/api/v1/holdings-review/dates', { params: { market } })).data.items);
  },
  async run(market: string): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post('/api/v1/holdings-review/run', null, { params: { market } })).data);
  },
};
