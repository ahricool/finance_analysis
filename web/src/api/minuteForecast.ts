import apiClient from './index';
import { toCamelCase } from './utils';

export interface ForecastBar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface MinuteForecast {
  symbol: string;
  model: string;
  weightsRevision: string;
  anchor: number;
  anchorClose: number;
  generatedAt: number;
  lookback: number;
  bars: ForecastBar[];
  closeReplay?: boolean;
  sessionClose?: number | null;
}

export interface MinuteForecastResponse {
  enabled: boolean;
  forecast: MinuteForecast | null;
  comparison: MinuteForecast | null;
  accuracy?: ForecastAccuracy | null;
}

export interface ForecastAccuracy {
  tradingDate: string;
  recent: {
    issuedAt: number;
    rows: Array<{ step: number; close: number; error: number; baselineError: number }>;
  } | null;
  daily: Array<{ step: number; count: number; mae: number; baselineMae: number }>;
}

export async function fetchMinuteForecast(symbol: string, signal: AbortSignal): Promise<MinuteForecastResponse> {
  const { data } = await apiClient.get(`/api/v1/market-data/minute-forecast/${encodeURIComponent(symbol)}`, { signal });
  return toCamelCase<MinuteForecastResponse>(data);
}

export interface MinuteForecastPreference {
  enabled: boolean;
}

function preferencePath(symbol: string) {
  return `/api/v1/market-data/minute-forecast/${encodeURIComponent(symbol)}/preference`;
}

export async function fetchMinuteForecastPreference(symbol: string, signal?: AbortSignal): Promise<MinuteForecastPreference> {
  const { data } = await apiClient.get(preferencePath(symbol), { signal });
  return toCamelCase<MinuteForecastPreference>(data);
}

export async function saveMinuteForecastPreference(symbol: string, enabled: boolean): Promise<MinuteForecastPreference> {
  const { data } = await apiClient.put(preferencePath(symbol), { enabled });
  return toCamelCase<MinuteForecastPreference>(data);
}
