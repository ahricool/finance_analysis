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
}

export interface MinuteForecastResponse {
  enabled: boolean;
  forecast: MinuteForecast | null;
  comparison: MinuteForecast | null;
}

export async function fetchMinuteForecast(symbol: string, signal: AbortSignal): Promise<MinuteForecastResponse> {
  const { data } = await apiClient.get(`/api/v1/market-data/minute-forecast/${encodeURIComponent(symbol)}`, { signal });
  return toCamelCase<MinuteForecastResponse>(data);
}
