import apiClient from './index';

export type MarketType = 'CN' | 'US' | 'HK';

export interface WatchListItem {
  id: number;
  code: string;
  name: string | null;
  notes: string | null;
  market_type: MarketType;
  is_favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface WatchListResponse {
  items: WatchListItem[];
  total: number;
}

export interface WatchListItemCreate {
  code: string;
  name?: string;
  notes?: string;
  market_type?: MarketType;
  is_favorite?: boolean;
}

export interface WatchListItemUpdate {
  name?: string;
  notes?: string;
  market_type?: MarketType;
  is_favorite?: boolean;
}

export const watchListApi = {
  async list(): Promise<WatchListResponse> {
    const res = await apiClient.get('/api/v1/watch-list');
    return res.data as WatchListResponse;
  },

  async create(body: WatchListItemCreate): Promise<WatchListItem> {
    const res = await apiClient.post('/api/v1/watch-list', body);
    return res.data as WatchListItem;
  },

  async update(id: number, body: WatchListItemUpdate): Promise<WatchListItem> {
    const res = await apiClient.put(`/api/v1/watch-list/${id}`, body);
    return res.data as WatchListItem;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/watch-list/${id}`);
  },
};
