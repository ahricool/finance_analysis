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
  assetType: string;
  quantity: string;
  averageCost: string;
  currentPrice?: string | null;
  marketValue?: string | null;
  weight?: string | null;
  unrealizedPnl?: string | null;
  openedAt?: string | null;
  closedAt?: string | null;
  tradeEngineEnabled?: boolean;
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
}

export interface TradeMarkerView {
  timestamp: string;
  type: 'B' | 'S' | 'T';
  operations: Array<{ executedAt: string; side: string; quantity: string; price: string }>;
}

export interface TradeEnginePosition {
  accountId: string;
  positionId: string;
  symbol: string;
  source: string;
  strategies?: string[];
  tradeEngineEnabled?: boolean;
  action: string | null;
  suggestedQuantity?: string | null;
  suggestedTargetQuantity: string | null;
  reason: string | null;
  llmReason?: string | null;
  profitStage: string | null;
  activeStop: string | null;
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
  async updatePosition(positionId: number, body: { tradeEngineEnabled?: boolean }) {
    const payload: Record<string, unknown> = {};
    if (body.tradeEngineEnabled !== undefined) payload.trade_engine_enabled = body.tradeEngineEnabled;
    const { data } = await apiClient.patch(`/api/v1/holdings/positions/${positionId}`, payload);
    return toCamelCase(data) as PortfolioPosition;
  },
};

export interface TradeSignal {
  id: number; symbol: string; positionId: string; action: string; evaluatedAt: string;
  strategyKey: string; strategyVersion: string; reason: string; llmReason: string | null;
  suggestedTargetQuantity: string | null;
  evidence: {
    currentQuantity?: string; targetQuantity?: string; portfolioReason?: string;
    strategySignals?: Array<{ strategyKey: string; action: string; reason: string }>;
    portfolioRisk?: { grossExposure?: string | null; maxGrossExposure?: string | null;
      position?: { weight?: string | null; maxWeight?: string | null; openRisk?: string | null; riskLimit?: string | null } | null };
  };
}

export const tradeEngineApi = {
  async positions(market?: string): Promise<TradeEnginePosition[]> {
    const { data } = await apiClient.get('/api/v1/trade-engine/positions', { params: market ? { market } : {} });
    return (data.items || []).map((item: unknown) => toCamelCase(item));
  },
  async signals(market?: string, positionId?: string): Promise<TradeSignal[]> {
    const { data } = await apiClient.get('/api/v1/trade-engine/signals', {
      params: { ...(market ? { market } : {}), ...(positionId ? { position_id: positionId } : {}) },
    });
    return (data.items || []).map((item: unknown) => toCamelCase(item));
  },
  async strategies(market: string) {
    const { data } = await apiClient.get('/api/v1/trade-engine/strategies', { params: { market } });
    return data.items || [];
  },
  async run(market: string) {
    const { data } = await apiClient.post('/api/v1/trade-engine/run', null, { params: { market } });
    return data;
  },
};
