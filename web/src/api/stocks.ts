import apiClient from './index';
import { toCamelCase } from './utils';

export type InstrumentSearchItem = {
  code: string;
  nativeCode: string;
  name: string;
  market: 'CN' | 'US' | 'HK' | string;
  instrumentType: string;
  matchType: 'exact' | 'prefix' | 'fuzzy' | string;
};

export type InstrumentSearchResponse = {
  items: InstrumentSearchItem[];
};

export type StockIndexMembership = {
  key: string;
  name: string;
  source: string;
};

export type StockClassification = {
  code: string;
  market: string;
  memberships: { indices: StockIndexMembership[] };
};

export const stocksApi = {
  async classification(code: string, signal?: AbortSignal): Promise<StockClassification> {
    const { data } = await apiClient.get<StockClassification>(
      `/api/v1/stocks/${encodeURIComponent(code)}/classification`, { signal },
    );
    return data;
  },
  async searchInstruments(
    query: string,
    options: { limit?: number; signal?: AbortSignal } = {},
  ): Promise<InstrumentSearchItem[]> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/stocks/search', {
      params: { q: query, limit: options.limit ?? 10 },
      signal: options.signal,
    });
    return toCamelCase<InstrumentSearchResponse>(data).items ?? [];
  },
};
