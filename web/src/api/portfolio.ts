import apiClient from './index';

export type PortfolioMarket = 'CN' | 'HK' | 'US';
export type PortfolioCurrency = 'CNY' | 'HKD' | 'USD';
export type PortfolioAssetType = 'STOCK' | 'ETF' | 'OPTION';
export type PositionStatus = 'OPEN' | 'CLOSED' | 'EXPIRED';

export interface PortfolioAccount {
  id: number;
  account_code: PortfolioMarket;
  name: string;
  market: PortfolioMarket;
  currency: PortfolioCurrency;
  cash_balance: string;
}

export interface PortfolioOptionContract {
  underlying_canonical_symbol: string;
  underlying_display_symbol: string;
  underlying_name: string | null;
  option_type: 'CALL' | 'PUT';
  expiration_date: string;
  strike_price: string;
  days_to_expiration: number;
  expiration_action_required: boolean;
}

export interface PortfolioPosition {
  id: number;
  account_id: number;
  account_code: PortfolioMarket;
  asset_type: PortfolioAssetType;
  market: PortfolioMarket;
  currency: PortfolioCurrency;
  canonical_symbol: string;
  display_symbol: string;
  name: string | null;
  quantity: string;
  position_side: 'LONG' | 'SHORT';
  avg_cost: string;
  contract_multiplier: string;
  cost_amount: string;
  opened_at: string | null;
  status: PositionStatus;
  closed_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  option: PortfolioOptionContract | null;
}

export interface EquityPositionCreate {
  canonical_symbol: string;
  display_symbol: string;
  name?: string;
  asset_type: 'STOCK' | 'ETF';
  quantity: string;
  avg_cost: string;
  opened_at?: string | null;
  notes?: string | null;
}

export interface OptionPositionCreate {
  underlying_canonical_symbol: string;
  underlying_display_symbol: string;
  underlying_name?: string;
  underlying_asset_type: 'STOCK' | 'ETF';
  option_type: 'CALL' | 'PUT';
  expiration_date: string;
  strike_price: string;
  quantity: string;
  avg_cost: string;
  contract_multiplier: string;
  opened_at?: string | null;
  notes?: string | null;
}

export interface PositionUpdate {
  quantity?: string;
  avg_cost?: string;
  opened_at?: string | null;
  status?: PositionStatus;
  closed_at?: string | null;
  notes?: string | null;
}

export const portfolioApi = {
  async listAccounts(): Promise<PortfolioAccount[]> {
    const response = await apiClient.get('/api/v1/portfolio/accounts');
    return response.data as PortfolioAccount[];
  },

  async updateCash(accountId: number, balance: string): Promise<PortfolioAccount> {
    const response = await apiClient.put(`/api/v1/portfolio/accounts/${accountId}/cash`, { balance });
    return response.data as PortfolioAccount;
  },

  async listPositions(
    accountId: number,
    status: PositionStatus | 'ALL' = 'OPEN',
    assetType: PortfolioAssetType | 'ALL' = 'ALL',
  ): Promise<PortfolioPosition[]> {
    const response = await apiClient.get(`/api/v1/portfolio/accounts/${accountId}/positions`, {
      params: { status, asset_type: assetType },
    });
    return response.data as PortfolioPosition[];
  },

  async createEquity(accountId: number, body: EquityPositionCreate): Promise<PortfolioPosition> {
    const response = await apiClient.post(
      `/api/v1/portfolio/accounts/${accountId}/positions/equities`,
      body,
    );
    return response.data as PortfolioPosition;
  },

  async createOption(accountId: number, body: OptionPositionCreate): Promise<PortfolioPosition> {
    const response = await apiClient.post(
      `/api/v1/portfolio/accounts/${accountId}/positions/options`,
      body,
    );
    return response.data as PortfolioPosition;
  },

  async updatePosition(positionId: number, body: PositionUpdate): Promise<PortfolioPosition> {
    const response = await apiClient.put(`/api/v1/portfolio/positions/${positionId}`, body);
    return response.data as PortfolioPosition;
  },

  async removePosition(positionId: number): Promise<void> {
    await apiClient.delete(`/api/v1/portfolio/positions/${positionId}`);
  },
};
