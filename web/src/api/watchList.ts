import apiClient from './index';
import { toCamelCase } from './utils';

export type MarketType = 'CN' | 'US' | 'HK';

export interface WatchListTag { id: number; name: string }
export type WatchListTagInput = { id: number } | { name: string };
export interface WatchListTagDraft { id?: number; name: string }
export interface WatchListFilters { market?: MarketType; tagId?: number; ungrouped?: boolean }

export interface WatchListItem {
  id: number;
  code: string;
  name: string | null;
  notes: string | null;
  marketType: MarketType;
  isFavorite: boolean;
  createdAt: string;
  updatedAt: string;
  validationError?: string | null;
  tags: WatchListTag[];
}

export interface WatchListResponse {
  items: WatchListItem[];
  total: number;
}

export interface WatchListItemCreate {
  code: string;
  name?: string;
  notes?: string;
  marketType?: MarketType;
  isFavorite?: boolean;
  tags?: WatchListTagInput[];
}

export interface WatchListItemUpdate {
  name?: string;
  notes?: string;
  marketType?: MarketType;
  isFavorite?: boolean;
  tags?: WatchListTagInput[];
}

function toWireBody({ marketType, isFavorite, ...rest }: WatchListItemCreate | WatchListItemUpdate) {
  return { ...rest, market_type: marketType, is_favorite: isFavorite };
}

export const watchListApi = {
  async listTags(): Promise<WatchListTag[]> {
    return (await apiClient.get('/api/v1/watch-list/tags')).data;
  },
  async createTag(name: string): Promise<WatchListTag> {
    return (await apiClient.post('/api/v1/watch-list/tags', { name })).data;
  },
  async renameTag(id: number, name: string): Promise<WatchListTag> {
    return (await apiClient.put(`/api/v1/watch-list/tags/${id}`, { name })).data;
  },
  async deleteTag(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/watch-list/tags/${id}`);
  },
  async list(filters: WatchListFilters = {}, signal?: AbortSignal): Promise<WatchListResponse> {
    const res = await apiClient.get('/api/v1/watch-list', {
      params: { market: filters.market, tag_id: filters.tagId, ungrouped: filters.ungrouped || undefined }, signal,
    });
    return toCamelCase<WatchListResponse>(res.data);
  },

  async create(body: WatchListItemCreate): Promise<WatchListItem> {
    const res = await apiClient.post('/api/v1/watch-list', toWireBody(body));
    return toCamelCase<WatchListItem>(res.data);
  },

  async update(id: number, body: WatchListItemUpdate): Promise<WatchListItem> {
    const res = await apiClient.put(`/api/v1/watch-list/${id}`, toWireBody(body));
    return toCamelCase<WatchListItem>(res.data);
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/api/v1/watch-list/${id}`);
  },
};
