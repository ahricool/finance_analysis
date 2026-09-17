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

export interface HoldingsLeg {
  accountId: string;
  positionId: string;
  legId: string;
  legRole: 'CORE' | 'ADDON';
  symbol: string;
  canonicalSymbol: string | null;
  assetType: string;
  quantity: string;
  entryPrice: string;
  entryTime: string;
  status: 'OPEN' | 'CLOSED';
  coverage: string;
  coverageReason: string | null;
  initialStop: string | null;
}

export interface HoldingsPosition {
  accountId: string;
  positionId: string;
  symbol: string;
  canonicalSymbol: string | null;
  assetType: string;
  legs: HoldingsLeg[];
}

export interface HoldingsAccount {
  accountId: string;
  accountName: string;
  baseCurrency: string;
  netAsset: string | null;
  validity: string;
  positionsComplete: boolean;
}

export interface HoldingsSnapshot {
  status: string;
  generation: number;
  accounts: HoldingsAccount[];
  positions: HoldingsPosition[];
  uncoveredLegs: HoldingsLeg[];
  warnings: string[];
}

export interface RiskPositionView {
  accountId: string;
  positionId: string;
  symbol: string;
  planStatus: string;
  planAction: string;
  planRevision: number;
  rowVersion: number;
  lastBarEnd: string | null;
  lastQuoteAsOf: string | null;
  activePlan: Record<string, unknown> | null;
  legsState: Record<string, unknown> | null;
}

export interface RiskEventView {
  id: number;
  eventType: string;
  action: string;
  positionId: string;
  legId: string | null;
  targetQuantity: string | null;
  createdAt: string;
  notificationId: number | null;
  pushStatus: string;
  evidence: Record<string, unknown>;
}

export interface HoldingsPolicy {
  policy: {
    maxSymbolWeight?: number;
    riskPerSymbol?: number;
    totalOpenRisk?: number;
    maxGrossExposure?: number;
    vwapMode?: string;
  };
  policyVersion: number;
}

export const holdingsApi = {
  async source(): Promise<HoldingsSource> {
    const { data } = await apiClient.get('/api/v1/holdings/source');
    return toCamelCase(data);
  },
  async connect(spreadsheetId: string, returnPath = '/market/holdings') {
    const { data } = await apiClient.post('/api/v1/holdings/connect', {
      spreadsheet_id: spreadsheetId,
      return_path: returnPath,
    });
    return data as { authorization_url: string; return_path: string; auth_status: string };
  },
  async disconnect() {
    const { data } = await apiClient.post('/api/v1/holdings/disconnect');
    return data;
  },
  async sync() {
    const { data } = await apiClient.post('/api/v1/holdings/sync');
    return data as { task_id: string | null; status: string; changed?: boolean; generation?: number };
  },
  async snapshot(): Promise<{ status: string; snapshot: HoldingsSnapshot | null }> {
    const { data } = await apiClient.get('/api/v1/holdings/snapshot');
    return { status: data.status, snapshot: data.snapshot ? toCamelCase(data.snapshot) : null };
  },
  async policy(): Promise<HoldingsPolicy> {
    const { data } = await apiClient.get('/api/v1/holdings/policy');
    return toCamelCase(data);
  },
  async updatePolicy(policy: Record<string, unknown>): Promise<HoldingsPolicy> {
    const { data } = await apiClient.put('/api/v1/holdings/policy', policy);
    return toCamelCase(data);
  },
  async risk() {
    const { data } = await apiClient.get('/api/v1/holdings/risk');
    return {
      source: data.source,
      snapshot: data.snapshot ? toCamelCase(data.snapshot) : null,
      positions: (data.positions || []).map((item: unknown) => toCamelCase(item)) as RiskPositionView[],
      events: (data.events || []).map((item: unknown) => toCamelCase(item)) as RiskEventView[],
    };
  },
  async runRisk() {
    const { data } = await apiClient.post('/api/v1/holdings/risk/run');
    return data;
  },
  async cancelPlan(body: {
    accountId: string;
    positionId: string;
    expectedStateVersion: number;
    reason: string;
  }) {
    const { data } = await apiClient.post('/api/v1/holdings/plans/cancel', {
      account_id: body.accountId,
      position_id: body.positionId,
      expected_state_version: body.expectedStateVersion,
      reason: body.reason,
    });
    return data;
  },
  async rebase(body: {
    accountId: string;
    positionId: string;
    legId: string;
    expectedSourceVersion: number;
    expectedStateVersion: number;
    reason: string;
  }) {
    const { data } = await apiClient.post('/api/v1/holdings/legs/rebase', {
      account_id: body.accountId,
      position_id: body.positionId,
      leg_id: body.legId,
      expected_source_version: body.expectedSourceVersion,
      expected_state_version: body.expectedStateVersion,
      reason: body.reason,
    });
    return data;
  },
};
