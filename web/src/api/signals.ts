import type {
  SignalDirection,
  SignalItem,
  SignalListResponse,
  SignalMarket,
} from '@/types/signals';
import apiClient from './index';
import { toCamelCase } from './utils';

export type SignalListQuery = {
  page?: number;
  pageSize?: number;
  market?: SignalMarket;
  direction?: SignalDirection;
  signalType?: string;
  keyword?: string;
  signalAtFrom?: string;
  signalAtTo?: string;
};

function toParams(query: SignalListQuery = {}) {
  return {
    page: query.page,
    page_size: query.pageSize,
    market: query.market,
    direction: query.direction,
    signal_type: query.signalType || undefined,
    keyword: query.keyword || undefined,
    signal_at_from: query.signalAtFrom,
    signal_at_to: query.signalAtTo,
  };
}

export const signalsApi = {
  async list(query?: SignalListQuery): Promise<SignalListResponse> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/signals', {
      params: toParams(query),
    });
    return toCamelCase<SignalListResponse>(data);
  },

  async get(signalId: number): Promise<SignalItem> {
    const { data } = await apiClient.get<Record<string, unknown>>(
      `/api/v1/signals/${signalId}`,
    );
    return toCamelCase<SignalItem>(data);
  },
};
