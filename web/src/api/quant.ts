import apiClient from './index';
import { toCamelCase } from './utils';
import type { IntradayConfirmation, MarketRegime, ModelRun, Portfolio, QuantCapabilities, QuantEvent, QuantSignal, QuantUniverse, SectorRegime, SignalRanking } from '@/types/quant';

export const quantApi = {
  async capabilities(): Promise<QuantCapabilities> { const { data } = await apiClient.get('/api/v1/quant/capabilities'); return toCamelCase(data); },
  async universes(): Promise<QuantUniverse[]> { const { data } = await apiClient.get('/api/v1/quant/universes'); return toCamelCase(data); },
  async marketRegime(): Promise<MarketRegime> { const { data } = await apiClient.get('/api/v1/quant/market-regime/latest'); return toCamelCase(data); },
  async marketRegimeHistory(): Promise<MarketRegime[]> { const { data } = await apiClient.get('/api/v1/quant/market-regime/history'); return toCamelCase(data); },
  async sectors(): Promise<SectorRegime[]> { const { data } = await apiClient.get('/api/v1/quant/sectors/ranking'); return toCamelCase(data); },
  async signals(universe = 'us_ai_semiconductor'): Promise<SignalRanking> { const { data } = await apiClient.get('/api/v1/quant/signals/ranking', { params: { universe } }); return toCamelCase(data); },
  async signal(code: string): Promise<QuantSignal> { const { data } = await apiClient.get(`/api/v1/quant/signals/${code}`); return toCamelCase(data); },
  async signalHistory(code: string): Promise<QuantSignal[]> { const { data } = await apiClient.get(`/api/v1/quant/signals/${code}/history`); return toCamelCase(data); },
  async models(): Promise<ModelRun[]> { const { data } = await apiClient.get('/api/v1/quant/model-runs'); return toCamelCase(data); },
  async model(id: number): Promise<ModelRun> { const { data } = await apiClient.get(`/api/v1/quant/model-runs/${id}`); return toCamelCase(data); },
  async publish(id: number, reason: string): Promise<ModelRun> { const { data } = await apiClient.post(`/api/v1/quant/model-runs/${id}/publish`, { reason }); return toCamelCase(data); },
  async events(params: Record<string, unknown> = {}): Promise<{items: QuantEvent[]; total:number}> { const { data } = await apiClient.get('/api/v1/quant/events', { params }); const value=toCamelCase<{items:QuantEvent[];total:number}>(data); return value; },
  async importEvents(format: 'json'|'csv', payload: string): Promise<Record<string, unknown>> { const body = format === 'json' ? { format, items: JSON.parse(payload) } : { format, csv_content: payload }; const { data } = await apiClient.post('/api/v1/quant/events/import', body); return toCamelCase(data); },
  async portfolio(): Promise<Portfolio> { const { data } = await apiClient.get('/api/v1/quant/portfolios/latest'); return toCamelCase(data); },
  async confirmations(): Promise<IntradayConfirmation[]> { const { data } = await apiClient.get('/api/v1/quant/intraday-confirmations'); return toCamelCase(data); },
};
