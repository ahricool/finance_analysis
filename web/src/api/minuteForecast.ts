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

function forecastPath(symbol: string, contract: boolean) {
  const code = encodeURIComponent(symbol);
  return contract ? `/api/v1/crypto/contracts/${code}/forecast` : `/api/v1/market-data/minute-forecast/${code}`;
}

export async function fetchMinuteForecast(symbol: string, signal: AbortSignal, contract = false): Promise<MinuteForecastResponse> {
  const { data } = await apiClient.get(forecastPath(symbol, contract), { signal });
  return toCamelCase<MinuteForecastResponse>(data);
}

export interface MinuteForecastPreference {
  enabled: boolean;
}

function preferencePath(symbol: string, contract: boolean) {
  return forecastPath(symbol, contract) + '/preference';
}

export async function fetchMinuteForecastPreference(symbol: string, signal?: AbortSignal, contract = false): Promise<MinuteForecastPreference> {
  const { data } = await apiClient.get(preferencePath(symbol, contract), { signal });
  return toCamelCase<MinuteForecastPreference>(data);
}

export async function saveMinuteForecastPreference(symbol: string, enabled: boolean, contract = false): Promise<MinuteForecastPreference> {
  const { data } = await apiClient.put(preferencePath(symbol, contract), { enabled });
  return toCamelCase<MinuteForecastPreference>(data);
}
