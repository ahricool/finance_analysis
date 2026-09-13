import apiClient from './index';
import { toCamelCase } from './utils';
import { isAxiosError } from 'axios';

export interface MarketStructureSnapshot {
  market: 'CN' | 'US';
  tradeDate: string;
  expectedTradeDate: string;
  breadth: { breadthDivergence5D: number | null; benchmarkReturn5D: number | null;
    medianMemberReturn5D: number | null; memberPositiveRatio5D: number | null;
    memberAboveMa10Ratio: number | null; memberAboveMa20Ratio: number | null };
  rotation: { rotationVelocity1D: number | null; rotationVelocity3D: number | null; rotationVelocity5D: number | null };
  leadership: { leadershipConcentration1D: number | null; leadershipConcentration5D: number | null; leadershipHhi5D: number | null };
  metrics: { states: { breadth: string; rotation: string | null }; universeKey: string; memberCount: number;
    universeSize: number; dataCoverage: number; benchmarkCode: string };
}

export const marketStructureApi = {
  async snapshot(market: 'CN' | 'US', tradeDate?: string): Promise<MarketStructureSnapshot | null> {
    try {
      const { data } = await apiClient.get('/api/v1/market-structure', { params: { market, trade_date: tradeDate } });
      return toCamelCase(data);
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 404) return null;
      throw error;
    }
  },
};
