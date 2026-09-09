import apiClient from './index';
import { toCamelCase } from './utils';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

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
  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
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
