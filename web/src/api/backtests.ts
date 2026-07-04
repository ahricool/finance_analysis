import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  BacktestConfig,
  BacktestEngine,
  BacktestEquity,
  BacktestPreflight,
  BacktestRun,
  BacktestRunList,
  BacktestStrategy,
  BacktestSymbol,
  BacktestTrade,
} from '@/types/backtests';

function payload(config: BacktestConfig) {
  return {
    engine: config.engine,
    strategy_key: config.strategyKey,
    market: config.market,
    code: config.code,
    start_date: config.startDate,
    end_date: config.endDate,
    initial_cash: config.initialCash,
    benchmark_code: config.benchmarkCode || null,
    parameters: config.parameters,
  };
}

function normalizeRun(value: Record<string, unknown>): BacktestRun {
  const run = toCamelCase<BacktestRun>(value);
  run.parameters = (value.parameters as Record<string, number>) ?? {};
  run.engineConfig = (value.engine_config as Record<string, unknown>) ?? {};
  return run;
}

export const backtestsApi = {
  async engines(): Promise<BacktestEngine[]> {
    const { data } = await apiClient.get('/api/v1/backtests/engines');
    return toCamelCase<BacktestEngine[]>(data);
  },
  async strategies(engine?: string, market?: string): Promise<BacktestStrategy[]> {
    const { data } = await apiClient.get('/api/v1/backtests/strategies', { params: { engine, market } });
    return toCamelCase<BacktestStrategy[]>(data);
  },
  async symbols(market: string, engine: string, keyword = ''): Promise<BacktestSymbol[]> {
    const { data } = await apiClient.get('/api/v1/backtests/symbols', { params: { market, engine, keyword } });
    return toCamelCase<BacktestSymbol[]>(data);
  },
  async preflight(config: BacktestConfig): Promise<BacktestPreflight> {
    const { data } = await apiClient.post('/api/v1/backtests/preflight', payload(config));
    return toCamelCase<BacktestPreflight>(data);
  },
  async create(config: BacktestConfig): Promise<BacktestRun> {
    const { data } = await apiClient.post<Record<string, unknown>>('/api/v1/backtests/runs', payload(config));
    return normalizeRun(data);
  },
  async runs(page = 1, pageSize = 20): Promise<BacktestRunList> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/backtests/runs', {
      params: { page, page_size: pageSize },
    });
    const result = toCamelCase<BacktestRunList>(data);
    result.items = ((data.items as Record<string, unknown>[]) ?? []).map(normalizeRun);
    return result;
  },
  async run(id: number): Promise<BacktestRun> {
    const { data } = await apiClient.get<Record<string, unknown>>(`/api/v1/backtests/runs/${id}`);
    return normalizeRun(data);
  },
  async trades(id: number): Promise<BacktestTrade[]> {
    const { data } = await apiClient.get(`/api/v1/backtests/runs/${id}/trades`, { params: { page_size: 500 } });
    return toCamelCase<{ items: BacktestTrade[] }>(data).items;
  },
  async equity(id: number): Promise<BacktestEquity[]> {
    const { data } = await apiClient.get(`/api/v1/backtests/runs/${id}/equity`);
    return toCamelCase<{ items: BacktestEquity[] }>(data).items;
  },
};
