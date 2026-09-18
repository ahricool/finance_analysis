import apiClient from './index';
import { toCamelCase } from './utils';
export interface Promotion {
  sourceDate: string | null; targetDate: string; complete: boolean;
  numerator: number | null; denominator: number | null; ratio: number | null;
  promotedCodes: string[]; notPromotedCodes: string[];
}
export interface Observation {
  tradeDate: string; previousTradeDate: string | null; ruleVersion: string; scope: string;
  earlyTimeThreshold: string; state: string; heatScore: number | null; stateReasons: string[];
  upstreamTotal: number; excludedStCount: number; excludedNewCount: number; excludedUnionCount: number;
  unknownScopeCount: number; scopeComplete: boolean; boardsComplete: boolean;
  limitUpCount: number | null; firstBoardCount: number | null; multiBoardCount: number | null; highestBoard: number | null;
  boardDistribution: Record<string, number | null>; unconfirmedBoardCount: number;
  earlyLimitUpCount: number | null; validLimitUpTimeCount: number | null; timeCoverage: number | null;
  earlyLimitUpRatio: number | null; sealRetentionMedian: number | null;
  validSealRetentionCount: number | null; sealRetentionCoverage: number | null;
  sealMoneySum: number | null; validSealMoneyCount: number | null; sealMoneyCoverage: number | null;
  reasons: { reason: string; count: number }[]; promotions: Record<string, Promotion>;
  changes: Record<string, number | null>; quality: { optionalErrors?: Record<string, string> };
  supplements: Record<string, { total: number }>;
  sourceTimestamp: string; fetchedAt: string; generatedAt: string;
}
export interface Overview {
  tradeDate: string | null; expectedTradeDate: string; observation: Observation | null;
  industryTop: { tradeDate: string; industryCode: string; industryName: string; strengthScore: number; state: string }[];
}
export interface History { dates: string[]; items: (Observation | null)[] }
export interface PoolRow {
  thscode: string; name: string; isSt?: boolean | null; isNew?: boolean | null;
  inScope?: boolean | null; continueDayText?: string | null; consecutiveBoards?: number | null;
  priceChangeRatio?: number | null; priceChangeRatioPct?: number | null; limitUpTime?: string | null;
  sealMoney?: number | null; maxSealMoney?: number | null; sealRetention?: number | null;
  limitUpReason?: string | null; qualityIssues?: string[];
  firstLimitTime?: string | null; lastLimitTime?: string | null; openTimes?: number | null;
}
export interface Pool { tradeDate: string | null; kind: string; available: boolean; total: number | null;
  upstreamTotal: number | null; page: number; size: number; items: PoolRow[]; basis: string }
export interface Ladder {
  source: null | { tradeDate: string; sourceTimestamp: string; fetchedAt: string;
    window: { length: number; dateList: string[]; boardCaps: Record<string, number> };
    items: { date: string; boards: Record<string, { thscode: string; name: string; boardNum: number }[]> }[] };
}
const base = '/api/v1/market-sentiment';
export const marketSentimentApi = {
  async overview(tradeDate?: string): Promise<Overview> {
    return toCamelCase((await apiClient.get(`${base}/overview`, { params: { trade_date: tradeDate } })).data);
  },
  async history(endDate?: string): Promise<History> {
    return toCamelCase((await apiClient.get(`${base}/history`, { params: { end_date: endDate, days: 30 } })).data);
  },
  async dates(): Promise<string[]> { return (await apiClient.get(`${base}/dates`)).data; },
  async pool(params: { trade_date?: string; kind?: string; board?: string; q?: string; reason?: string; scope?: string; page?: number }): Promise<Pool> {
    return toCamelCase((await apiClient.get(`${base}/pool`, { params: { ...params, size: 50 } })).data);
  },
  async ladder(asOf?: string): Promise<Ladder> {
    return toCamelCase((await apiClient.get(`${base}/ladder`, { params: { as_of: asOf } })).data);
  },
  async run(params: { trade_date?: string; backfill_days?: number; missing_only?: boolean }): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post(`${base}/run`, params)).data);
  },
};
