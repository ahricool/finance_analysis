import apiClient from './index';
import { toCamelCase } from './utils';

export type HoldingsAuthStatus =
  | 'NOT_CONFIGURED'
  | 'DISCONNECTED'
  | 'PENDING'
  | 'CONNECTED'
  | 'CONNECTED_NO_OFFLINE'
  | 'NEEDS_REAUTH';

export interface HoldingsSource {
  googleConfigured: boolean;
  holdingsEnabled: boolean;
  missingConfig: string[];
  sourceId: number | null;
  spreadsheetId: string | null;
  schemaVersion: string | null;
  authStatus: HoldingsAuthStatus;
  syncStatus: string | null;
  enabled: boolean;
  lastAttemptAt: string | null;
  lastSuccessAt: string | null;
  lastErrorCode: string | null;
  publishedGeneration: number;
  contentHash: string | null;
  configVersion: number;
  policyVersion: number;
  canBackgroundSync: boolean;
}

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
  action: string | null;
  suggestedTargetQuantity: string | null;
  reason: string | null;
  profitStage: string | null;
  activeStop: string | null;
}

export const holdingsApi = {
  async summary(market: string): Promise<HoldingsSummary> {
    const { data } = await apiClient.get('/api/v1/holdings/summary', { params: { market } });
    return toCamelCase(data);
  },
  async buy(body: { accountId: number; symbol: string; quantity: string; price: string; executedAt?: string; assetType?: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/buy', {
      account_id: body.accountId,
      symbol: body.symbol,
      quantity: body.quantity,
      price: body.price,
      executed_at: body.executedAt,
      asset_type: body.assetType || 'STOCK',
    });
    return toCamelCase(data);
  },
  async sell(body: { positionId: number; quantity: string; price: string; executedAt?: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/sell', {
      position_id: body.positionId,
      quantity: body.quantity,
      price: body.price,
      executed_at: body.executedAt,
    });
    return toCamelCase(data);
  },
  async deposit(body: { accountId: number; amount: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/cash/deposit', { account_id: body.accountId, amount: body.amount });
    return toCamelCase(data);
  },
  async withdraw(body: { accountId: number; amount: string }) {
    const { data } = await apiClient.post('/api/v1/holdings/cash/withdraw', { account_id: body.accountId, amount: body.amount });
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
  async source(): Promise<HoldingsSource> {
    const { data } = await apiClient.get('/api/v1/holdings/google/source');
    return toCamelCase(data);
  },
  async connect(spreadsheetId: string, returnPath = '/market/holdings') {
    const { data } = await apiClient.post('/api/v1/holdings/google/connect', {
      spreadsheet_id: spreadsheetId,
      return_path: returnPath,
    });
    return data as { authorization_url: string; return_path: string; auth_status: string };
  },
  async disconnect() {
    const { data } = await apiClient.post('/api/v1/holdings/google/disconnect');
    return data;
  },
  async sync() {
    const { data } = await apiClient.post('/api/v1/holdings/google/sync');
    return data as { task_id: string | null; status: string; changed?: boolean; generation?: number };
  },
  async snapshot() {
    const { data } = await apiClient.get('/api/v1/holdings/snapshot');
    return { status: data.status, snapshot: data.snapshot ? toCamelCase(data.snapshot) : null };
  },
};

export const tradeEngineApi = {
  async positions(market?: string): Promise<TradeEnginePosition[]> {
    const { data } = await apiClient.get('/api/v1/trade-engine/positions', { params: market ? { market } : {} });
    return (data.items || []).map((item: unknown) => toCamelCase(item));
  },
  async signals(market?: string, positionId?: string) {
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
