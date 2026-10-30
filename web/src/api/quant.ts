import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  DatasetBuildAccepted,
  QuantRelease, QuantStatus, TrainingExperiment, TrainingPreflight,
  MarketRegime,
  ModelRun,
  ModelRunCreateAccepted,
  ModelRunCreatePayload,
  Portfolio,
  QuantCapabilities,
  QuantDatasetSnapshot,
  QuantDeleteResult,
  QuantMarket,
  QuantModelDefinition,
  QuantSignal,
  QuantUniverse,
  SignalRanking,
} from '@/types/quant';

const withMarket = (market: QuantMarket, params: Record<string, unknown> = {}) => ({ ...params, market });

export const quantApi = {
  async status(market: QuantMarket): Promise<QuantStatus> {
    const { data } = await apiClient.get('/api/v1/quant/status', { params: { market } });
    return toCamelCase(data);
  },
  async releases(market: QuantMarket): Promise<QuantRelease[]> {
    const { data } = await apiClient.get('/api/v1/quant/releases', { params: { market } });
    return toCamelCase(data);
  },
  async publishRelease(market: QuantMarket, crossSectionId: number, timeSeriesId: number, reason: string): Promise<QuantRelease> {
    const { data } = await apiClient.post('/api/v1/quant/releases', { market, cross_section_id: crossSectionId, time_series_id: timeSeriesId, reason });
    return toCamelCase(data);
  },
  async preflight(payload: TrainingExperiment): Promise<TrainingPreflight> {
    const { data } = await apiClient.post('/api/v1/quant/training/preflight', { market: payload.market, date_from: payload.dateFrom, date_to: payload.dateTo, model_version: payload.modelVersion });
    return toCamelCase(data);
  },
  async experiment(payload: TrainingExperiment): Promise<{ modelRunIds: number[]; taskId: string }> {
    const { data } = await apiClient.post('/api/v1/quant/training/experiments', { market: payload.market, date_from: payload.dateFrom, date_to: payload.dateTo, model_version: payload.modelVersion });
    return toCamelCase(data);
  },
  async dates(
    market: QuantMarket,
    scope: 'dashboard' | 'signals' | 'portfolios',
    code?: string,
  ): Promise<{ items: string[] }> {
    const { data } = await apiClient.get('/api/v1/quant/dates', {
      params: withMarket(market, { scope, code }),
    });
    return data;
  },
  async capabilities(market: QuantMarket = 'US'): Promise<QuantCapabilities> {
    const { data } = await apiClient.get('/api/v1/quant/capabilities', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async universes(market: QuantMarket = 'US'): Promise<QuantUniverse[]> {
    const { data } = await apiClient.get('/api/v1/quant/universes', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async marketRegime(market: QuantMarket = 'US', tradeDate?: string, modelVersion?: string): Promise<MarketRegime> {
    const { data } = await apiClient.get('/api/v1/quant/market-regime/latest', { params: withMarket(market, { trade_date: tradeDate, model_version: modelVersion }) });
    return toCamelCase(data);
  },
  async marketRegimeHistory(market: QuantMarket = 'US', dateTo?: string): Promise<MarketRegime[]> {
    const { data } = await apiClient.get('/api/v1/quant/market-regime/history', { params: withMarket(market, { date_to: dateTo }) });
    return toCamelCase(data);
  },
  async signals(market: QuantMarket = 'US', tradeDate?: string): Promise<SignalRanking> {
    const { data } = await apiClient.get('/api/v1/quant/signals/ranking', {
      params: withMarket(market, { trade_date: tradeDate }),
    });
    return toCamelCase(data);
  },
  async signal(code: string, market: QuantMarket = 'US', tradeDate?: string): Promise<QuantSignal> {
    const { data } = await apiClient.get(`/api/v1/quant/signals/${code}`, { params: withMarket(market, { trade_date: tradeDate }) });
    return toCamelCase(data);
  },
  async signalHistory(code: string, market: QuantMarket = 'US', dateTo?: string): Promise<QuantSignal[]> {
    const { data } = await apiClient.get(`/api/v1/quant/signals/${code}/history`, { params: withMarket(market, { date_to: dateTo }) });
    return toCamelCase(data);
  },
  async models(market: QuantMarket = 'US'): Promise<ModelRun[]> {
    const { data } = await apiClient.get('/api/v1/quant/model-runs', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async modelDefinitions(market: QuantMarket = 'US'): Promise<QuantModelDefinition[]> {
    const { data } = await apiClient.get('/api/v1/quant/models/definitions', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async datasets(market: QuantMarket = 'US'): Promise<QuantDatasetSnapshot[]> {
    const { data } = await apiClient.get('/api/v1/quant/datasets', { params: withMarket(market) });
    return toCamelCase(data);
  },
  async deleteDataset(id: number, market: QuantMarket = 'US'): Promise<QuantDeleteResult> {
    const { data } = await apiClient.delete(`/api/v1/quant/datasets/${id}`, {
      params: withMarket(market),
    });
    return toCamelCase(data);
  },
  async buildDataset(
    market: QuantMarket,
    dateFrom: string,
    dateTo: string,
  ): Promise<DatasetBuildAccepted> {
    const { data } = await apiClient.post('/api/v1/quant/datasets/build', {
      market,
      date_from: dateFrom,
      date_to: dateTo,
    });
    return toCamelCase(data);
  },
  async createModelRun(payload: ModelRunCreatePayload): Promise<ModelRunCreateAccepted> {
    const { data } = await apiClient.post('/api/v1/quant/model-runs', {
      market: payload.market,
      model_key: payload.modelKey,
      model_version: payload.modelVersion,
      dataset_snapshot_id: payload.datasetSnapshotId,
    });
    return toCamelCase(data);
  },
  async model(id: number, market: QuantMarket = 'US'): Promise<ModelRun> {
    const { data } = await apiClient.get(`/api/v1/quant/model-runs/${id}`, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async deleteModelRun(id: number, market: QuantMarket = 'US'): Promise<QuantDeleteResult> {
    const { data } = await apiClient.delete(`/api/v1/quant/model-runs/${id}`, {
      params: withMarket(market),
    });
    return toCamelCase(data);
  },
  async publish(id: number, reason: string, market: QuantMarket = 'US'): Promise<ModelRun> {
    const { data } = await apiClient.post(`/api/v1/quant/model-runs/${id}/publish`, { reason }, { params: withMarket(market) });
    return toCamelCase(data);
  },
  async portfolio(market: QuantMarket = 'US', tradeDate?: string): Promise<Portfolio> {
    const { data } = await apiClient.get('/api/v1/quant/portfolios/latest', { params: withMarket(market, { trade_date: tradeDate }) });
    return toCamelCase(data);
  },
};
