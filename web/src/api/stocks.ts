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
  memberships: { indices: StockIndexMembership[]; industries?: StockIndustryMembership[] };
};

export type StockIndustryMembership = {
  code: string;
  name: string;
  membersObservedAt: string;
};

type ClassificationRequest = {
  promise: Promise<StockClassification>;
  controller: AbortController;
  consumers: number;
  completed: boolean;
  expiresAt: number;
};
const classifications = new Map<string, ClassificationRequest>();

async function readClassification(code: string, signal?: AbortSignal): Promise<StockClassification> {
  if (signal?.aborted) throw new DOMException('Request aborted', 'AbortError');
  const now = Date.now();
  for (const [key, entry] of classifications) {
    if (entry.completed && entry.expiresAt <= now) classifications.delete(key);
  }
  const key = code.trim().toUpperCase();
  let entry = classifications.get(key);
  if (!entry) {
    const controller = new AbortController();
    const promise = apiClient.get(`/api/v1/stocks/${encodeURIComponent(key)}/classification`, { signal: controller.signal })
      .then(({ data }) => toCamelCase<StockClassification>(data));
    entry = { promise, controller, consumers: 0, completed: false, expiresAt: Infinity };
    const request = entry;
    classifications.set(key, request);
    void promise.then(() => {
      request.completed = true;
      request.expiresAt = Date.now() + 60_000;
    }, () => {
      request.completed = true;
      if (classifications.get(key) === request) classifications.delete(key);
    });
  }
  const request = entry;
  request.consumers++;
  let abort: (() => void) | undefined;
  try {
    const result = await new Promise<StockClassification>((resolve, reject) => {
      abort = () => reject(new DOMException('Request aborted', 'AbortError'));
      signal?.addEventListener('abort', abort, { once: true });
      void request.promise.then(resolve, reject);
    });
    // Consumers own their data; a list must not mutate the detail's cached reference.
    return structuredClone(result);
  } finally {
    if (abort) signal?.removeEventListener('abort', abort);
    request.consumers--;
    if (!request.completed && request.consumers === 0) {
      if (classifications.get(key) === request) classifications.delete(key);
      request.controller.abort();
    }
  }
}

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
    return readClassification(code, signal);
  },
  async searchInstruments(
    query: string,
    options: { limit?: number; signal?: AbortSignal; market?: MarketType } = {},
  ): Promise<InstrumentSearchItem[]> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/stocks/search', {
      params: { q: query, limit: options.limit ?? 10, market: options.market },
      signal: options.signal,
    });
    return toCamelCase<InstrumentSearchResponse>(data).items ?? [];
  },
};
