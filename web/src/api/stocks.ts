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

export const stocksApi = {
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
