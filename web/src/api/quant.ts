import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  IntradayConfirmation,
  MarketRegime,
  ModelRun,
  Portfolio,
  QuantCapabilities,
  QuantEvent,
  QuantMarket,
  QuantSignal,
  QuantUniverse,
  SectorRegime,
  SignalRanking,
} from '@/types/quant';

const withMarket = (market: QuantMarket, params: Record<string, unknown> = {}) => ({ ...params, market });

export const quantApi = {
  async capabilities(market: QuantMarket = 'US'): Promise<QuantCapabilities> {
    const { data } = await apiClient.get('/api/v1/quant/capabilities', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async universes(market: QuantMarket = 'US'): Promise<QuantUniverse[]> {
    const { data } = await apiClient.get('/api/v1/quant/universes', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async marketRegime(market: QuantMarket = 'US'): Promise<MarketRegime> {
    const { data } = await apiClient.get('/api/v1/quant/market-regime/latest', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async marketRegimeHistory(market: QuantMarket = 'US'): Promise<MarketRegime[]> {
    const { data } = await apiClient.get('/api/v1/quant/market-regime/history', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async sectors(market: QuantMarket = 'US'): Promise<SectorRegime[]> {
    const { data } = await apiClient.get('/api/v1/quant/sectors/ranking', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async signals(market: QuantMarket = 'US'): Promise<SignalRanking> {
    const { data } = await apiClient.get('/api/v1/quant/signals/ranking', {
      params: withMarket(market),
    });
    return toCamelCase(data);
  },
  async signal(code: string, market: QuantMarket = 'US'): Promise<QuantSignal> {
    const { data } = await apiClient.get(`/api/v1/quant/signals/${code}`, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async signalHistory(code: string, market: QuantMarket = 'US'): Promise<QuantSignal[]> {
    const { data } = await apiClient.get(`/api/v1/quant/signals/${code}/history`, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async models(market: QuantMarket = 'US'): Promise<ModelRun[]> {
    const { data } = await apiClient.get('/api/v1/quant/model-runs', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async model(id: number, market: QuantMarket = 'US'): Promise<ModelRun> {
    const { data } = await apiClient.get(`/api/v1/quant/model-runs/${id}`, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async publish(id: number, reason: string, market: QuantMarket = 'US'): Promise<ModelRun> {
    const { data } = await apiClient.post(`/api/v1/quant/model-runs/${id}/publish`, { reason }, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async events(market: QuantMarket = 'US', params: Record<string, unknown> = {}): Promise<{items: QuantEvent[]; total: number}> {
    const { data } = await apiClient.get('/api/v1/quant/events', { params: withMarket(market, params) });
    return toCamelCase<{items: QuantEvent[]; total: number}>(data);
  },
  async importEvents(format: 'json' | 'csv', payload: string): Promise<Record<string, unknown>> {
    const body = format === 'json' ? { format, items: JSON.parse(payload) } : { format, csv_content: payload };
    const { data } = await apiClient.post('/api/v1/quant/events/import', body);
    return toCamelCase(data);
  },
  async portfolio(market: QuantMarket = 'US'): Promise<Portfolio> {
    const { data } = await apiClient.get('/api/v1/quant/portfolios/latest', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async confirmations(market: QuantMarket = 'US'): Promise<IntradayConfirmation[]> {
    const { data } = await apiClient.get('/api/v1/quant/intraday-confirmations', { params: withMarket(market) });
    return toCamelCase(data);
  },
};
