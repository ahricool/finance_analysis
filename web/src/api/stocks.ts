import apiClient from './index';
import { toCamelCase } from './utils';
import type { RealtimeQuote } from './realtimeMarket';
import type { MarketType } from './watchList';

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
  async quote(code: string, market: MarketType, signal?: AbortSignal): Promise<RealtimeQuote> {
    const { data } = await apiClient.get(`/api/v1/stocks/${encodeURIComponent(code)}/quote`, { signal });
    const quote = toCamelCase<{
      stockCode: string; currentPrice: number; change?: number | null; changePercent?: number | null;
      open?: number | null; high?: number | null; low?: number | null; prevClose?: number | null;
      volume?: number | null; amount?: number | null; updateTime?: string | null;
    }>(data);
    return {
      code: quote.stockCode, symbol: quote.stockCode, market_type: market,
      available: Number.isFinite(quote.currentPrice) && quote.currentPrice > 0,
      last_price: quote.currentPrice, change_amount: quote.change, change_pct: quote.changePercent,
      open: quote.open, high: quote.high, low: quote.low, pre_close: quote.prevClose,
      volume: quote.volume, turnover: quote.amount, event_time: quote.updateTime,
    };
  },
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
