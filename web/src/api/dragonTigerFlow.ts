import apiClient from './index';
import { toCamelCase } from './utils';

export type FlowBoard = 'all' | 'org' | 'hot_money';
export interface FlowFilters { endDate: string; days: 1 | 5 | 10 | 20; board: FlowBoard; rangeDays: 1 | 3 }
export interface FlowAmounts { netValue: number | null; buyValue: number | null; sellValue: number | null;
  orgNetValue: number | null; hotMoneyNetValue: number | null }
export interface FlowConcept { id: string; name: string; netValue: number | null; orgNetValue: number | null;
  hotMoneyNetValue: number | null; stockCount: number; values: (number | null)[] }
export interface FlowEvidence extends FlowAmounts { symbol: string; name: string; tradeDate: string; rangeDays: 1 | 3;
  concepts: string[]; conceptId: string; conceptName: string; allocationCount: number;
  originalNetValue: number | null; stockNetValue: number | null }
export interface FlowHotMoneyDetail { symbol: string; name: string; tradeDate: string; rangeDays: 1 | 3;
  hotMoneyName: string; hotMoneyItemNetValue: number | null }
export interface FlowOverview {
  version: string; revision: string; board: FlowBoard; rangeDays: 1 | 3; tradeDate: string | null; expectedTradeDate?: string | null; dates: string[];
  complete: boolean; missingDates: string[]; excludedUndisclosedCount: number;
  summary: FlowAmounts & { stockCount: number; top5Concentration: number | null };
  concepts: FlowConcept[]; evidence: FlowEvidence[]; hotMoneyDetails: FlowHotMoneyDetail[];
  sourceQuality: { tradeDate: string; generatedAt: string; errors: Record<string, string>; sources: Record<string, unknown> }[];
  attribution: string; source: string; unit: string;
}
export interface FlowDate { tradeDate: string; generatedAt: string; boards: FlowBoard[]; errors: Record<string, string> }
export const flowBoardLabels: Record<FlowBoard, string> = { all: '全部榜', org: '机构榜', hot_money: '游资榜' };
export const dragonTigerFlowApi = {
  async run(params: { trade_date?: string; backfill_days?: number; missing_only?: boolean }): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post('/api/v1/dragon-tiger-flow/run', params)).data);
  },
  async overview(filters: FlowFilters): Promise<FlowOverview> {
    return toCamelCase((await apiClient.get('/api/v1/dragon-tiger-flow/overview', { params: {
      end_date: filters.endDate || undefined, days: filters.days, board: filters.board, range_days: filters.rangeDays,
    } })).data);
  },
  async dates(): Promise<FlowDate[]> {
    return toCamelCase((await apiClient.get('/api/v1/dragon-tiger-flow/dates')).data);
  },
};
