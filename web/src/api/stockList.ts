import apiClient from './index';

export type MarketType = 'CN' | 'US' | 'HK';

export interface StockHolding {
  id: number;
  code: string;
  name: string | null;
  quantity: string;
  avg_cost: string | null;
  opened_at: string | null;
  market_type: MarketType;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface StockListResponse {
  items: StockHolding[];
  total: number;
}

export interface StockHoldingCreate {
  code: string;
  name?: string;
  quantity?: string;
  avg_cost?: string | null;
  opened_at?: string | null;
  market_type?: MarketType;
  notes?: string;
}

export interface StockHoldingUpdate {
  name?: string;
  quantity?: string;
  avg_cost?: string | null;
  opened_at?: string | null;
  notes?: string;
}

export const stockListApi = {
  async list(): Promise<StockListResponse> {
    const res = await apiClient.get('/api/v1/stock-list');
    return res.data as StockListResponse;
  },

  async create(body: StockHoldingCreate): Promise<StockHolding> {
    const res = await apiClient.post('/api/v1/stock-list', body);
    return res.data as StockHolding;
  },

  async update(id: number, body: StockHoldingUpdate): Promise<StockHolding> {
    const res = await apiClient.put(`/api/v1/stock-list/${id}`, body);
    return res.data as StockHolding;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/stock-list/${id}`);
  },
};
