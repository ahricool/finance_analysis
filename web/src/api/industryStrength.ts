import apiClient from './index';
import { toCamelCase } from './utils';

export type IndustryState = 'EMERGING' | 'STRONG' | 'NEUTRAL' | 'COOLING' | 'WEAK';
export interface IndustrySnapshot {
  tradeDate: string; industryCode: string; industryName: string; state: IndustryState;
  close: number; ret1D: number; ret5D: number; ret10D: number; ret20D: number;
  rs5D: number; rs10D: number; rs20D: number; strengthScore: number; strengthRank: number;
  rankChange1D: number | null; rankChange3D: number | null; rankChange5D: number | null;
  previous5DReturn: number; momentumAcceleration5D: number; accelerationPercentile: number;
  turnoverRatio5D: number; constituentCount: number | null; dailyValidCount: number | null; ma5ValidCount: number | null; aboveMa5Count: number | null; ma20ValidCount: number | null; aboveMa20Count: number | null;
  upCount: number | null; downCount: number | null; flatCount: number | null; upRatio: number | null;
  aboveMa5Ratio: number | null; aboveMa20Ratio: number | null; equalWeightReturn: number | null;
  dataTimestamp: string; membersObservedAt: string | null; createdAt: string; updatedAt: string;
  quality: { breadthStatus?: string; dailyBreadthCoverage: number; ma5Coverage: number; ma20Coverage: number; catalogCount: number; rankedCount: number; coverage: number; excluded: Record<string, string> };
}
export interface IndustryRanking { tradeDate: string | null; expectedTradeDate: string; source: string; items: IndustrySnapshot[] }
export interface IndustryHistory { dates: string[]; items: IndustrySnapshot[] }
export interface IndustryDetail { current: IndustrySnapshot; history: IndustrySnapshot[] }
export interface Constituent {
  code: string; name: string; price: number | null; changePct: number | null; volume: number | null;
  amount: number | null; trendRank: number | null; aboveMa5: boolean | null; aboveMa20: boolean | null;
}
export interface Constituents { trendRankDate?: string | null; industryCode: string; updatedAt: string | null;
  constituentCount: number; dailyValidCount: number; ma5ValidCount: number; aboveMa5Count: number; ma20ValidCount: number; aboveMa20Count: number; items: Constituent[] }
export interface IndustryPreview {
  status: string; error: string | null;
  result: (IndustryRanking & { generatedAt: string; dataAsOf: string; dataLatestAt: string; constituents: Record<string, Constituents> }) | null;
}
const base = '/api/v1/industry-strength';
export const industryStrengthApi = {
  async preview(): Promise<IndustryPreview> {
    const result = toCamelCase<IndustryPreview>((await apiClient.get(`${base}/preview`)).data);
    if (result.result) {
      // Dynamic symbol keys must not be camel-cased (881101.TI -> 881101Ti).
      result.result.constituents = Object.fromEntries(
        Object.values(result.result.constituents).map(item => [item.industryCode, item]),
      );
    }
    return result;
  },
  async ranking(tradeDate?: string): Promise<IndustryRanking> {
    return toCamelCase((await apiClient.get(`${base}/ranking`, { params: { trade_date: tradeDate } })).data);
  },
  async dates(): Promise<string[]> { return (await apiClient.get(`${base}/dates`)).data; },
  async history(tradeDate?: string): Promise<IndustryHistory> {
    return toCamelCase((await apiClient.get(`${base}/history`, { params: { trade_date: tradeDate } })).data);
  },
  async detail(code: string, tradeDate?: string): Promise<IndustryDetail> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}`, { params: { trade_date: tradeDate } })).data);
  },
  async constituents(code: string): Promise<Constituents> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}/constituents`)).data);
  },
};
