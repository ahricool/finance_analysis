import apiClient from './index';
import { toCamelCase } from './utils';

export type HeatmapMarket = 'CN' | 'US';
export interface HeatmapStock {
  code: string; name: string; marketCap: number; price: number | null; changePct: number | null;
  groupCode: string; groupName: string; quoteTime: string | null;
}
export interface HeatmapSnapshot {
  market: HeatmapMarket; source: string; generatedAt: string; dataAsOf: string | null; dataLatestAt: string | null;
  classificationObservedAt: string | null; minMarketCap: number; refreshSeconds: number;
  excludedCount: number; unclassifiedCount: number; items: HeatmapStock[];
}
export interface HeatmapResponse { status: 'ready' | 'empty' | 'stale'; snapshot: HeatmapSnapshot | null }
export async function getMarketHeatmap(market: HeatmapMarket): Promise<HeatmapResponse> {
  return toCamelCase((await apiClient.get('/api/v1/market-heatmap', { params: { market } })).data);
}
