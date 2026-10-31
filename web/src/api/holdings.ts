import apiClient from './index';
import { toCamelCase } from './utils';

export interface PortfolioAccount {
  id: number;
  name: string;
  market: string;
  cash: string;
  currency: string;
}

export interface PortfolioPosition {
  id: number;
  accountId: number;
  market: string;
  symbol: string;
  name?: string | null;
  assetType: string;
  quantity: string;
  averageCost: string;
  currentPrice?: string | null;
  marketValue?: string | null;
  weight?: string | null;
  unrealizedPnl?: string | null;
  unrealizedPnlPct?: string | null;
  changeAmount?: string | null;
  changePct?: string | null;
  dayPnl?: string | null;
  quoteTime?: string | null;
  quoteSource?: string | null;
  quoteStatus?: 'current' | 'delayed' | 'unavailable';
  openedAt?: string | null;
  closedAt?: string | null;
  lots?: Array<{ id: number; role: string; remainingQuantity: string; entryPrice: string }>;
}

export interface HoldingsSummary {
  market: string;
  accounts: PortfolioAccount[];
  cash: string;
  marketValue: string;
  totalAsset: string;
  grossExposure: string | null;
  positions: PortfolioPosition[];
  missingQuoteCount?: number;
  generatedAt?: string;
}

export interface TradeMarkerView {
  timestamp: string;
  type: 'B' | 'S' | 'T';
  operations: Array<{ executedAt: string; side: string; quantity: string; price: string }>;
}

export const holdingsApi = {
  async summary(market: string): Promise<HoldingsSummary> {
    const { data } = await apiClient.get('/api/v1/holdings/summary', { params: { market } });
    return toCamelCase(data);
  },
  async buy(body: { operationId: string; accountId: number; symbol: string; quantity: string; price: string; executedAt?: string; assetType?: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/buy', {
      operation_id: body.operationId,
      account_id: body.accountId,
      symbol: body.symbol,
      quantity: body.quantity,
      price: body.price,
      executed_at: body.executedAt,
      asset_type: body.assetType || 'STOCK',
    });
    return toCamelCase(data);
  },
  async sell(body: { operationId: string; positionId: number; quantity: string; price: string; executedAt?: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/sell', {
      operation_id: body.operationId,
      position_id: body.positionId,
      quantity: body.quantity,
      price: body.price,
      executed_at: body.executedAt,
    });
    return toCamelCase(data);
  },
  async setCash(body: { operationId: string; accountId: number; amount: string }) {
    const { data } = await apiClient.patch('/api/v1/holdings/cash', { operation_id: body.operationId, account_id: body.accountId, amount: body.amount });
    return toCamelCase(data);
  },
  async operations(positionId: number) {
    const { data } = await apiClient.get(`/api/v1/holdings/positions/${positionId}/operations`);
    return (data.items || []).map((item: unknown) => toCamelCase(item));
  },
  async markers(positionId: number): Promise<TradeMarkerView[]> {
    const { data } = await apiClient.get(`/api/v1/holdings/positions/${positionId}/markers`);
    return (data.items || []).map((item: unknown) => toCamelCase(item));
  },
};
