import apiClient from './index';
import { toCamelCase } from './utils';

export type IndustryState = 'EMERGING' | 'STRONG' | 'NEUTRAL' | 'COOLING' | 'WEAK';
export interface IndustrySnapshot {
  tradeDate: string; industryCode: string; industryName: string; state: IndustryState;
  close: number; ret1D: number; ret5D: number; ret10D: number; ret20D: number;
  rs5D: number; rs10D: number; rs20D: number; strengthScore: number; strengthRank: number;
  rankChange1D: number | null; rankChange3D: number | null; rankChange5D: number | null;
  previous5DReturn: number; momentumAcceleration5D: number; accelerationPercentile: number;
  turnoverRatio5D: number; constituentCount: number; validConstituentCount: number;
  upCount: number; downCount: number; flatCount: number; upRatio: number;
  aboveMa5Ratio: number; aboveMa20Ratio: number; equalWeightReturn: number;
  dataTimestamp: string; membersObservedAt: string; createdAt: string; updatedAt: string;
  quality: { catalogCount: number; rankedCount: number; coverage: number; excluded: Record<string, string> };
}
export interface IndustryRanking { tradeDate: string | null; expectedTradeDate: string; source: string; items: IndustrySnapshot[] }
export interface IndustryHistory { dates: string[]; items: IndustrySnapshot[] }
export interface IndustryDetail { current: IndustrySnapshot; history: IndustrySnapshot[] }
export interface Constituent {
  code: string; name: string; price: number | null; changePct: number | null; volume: number | null;
  amount: number | null; aboveMa5: boolean | null; aboveMa20: boolean | null;
}
export interface Constituents { industryCode: string; tradeDate: string; membersObservedAt: string;
  constituentCount: number; validConstituentCount: number; items: Constituent[] }
const base = '/api/v1/industry-strength';
export const industryStrengthApi = {
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
