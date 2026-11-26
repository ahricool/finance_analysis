import apiClient from './index';

export type Environment = 'paper' | 'live';
interface Period {
  environment: Environment; start: string; end: string | null;
  start_equity: number; end_equity: number | null; profit: number | null;
}
interface Strategy {
  parameters?: {symbol: string; notional: string; stop_pct: string; max_loss: string; leverage_limit: number};
  key: string; name: string; description: string; backtest: number | null;
  paper: number | null; live: number | null; periods: Period[];
}
export interface Catalog { items: Strategy[]; selected: Record<Environment, string | null>; interval_seconds: number }
const path = '/api/v1/crypto/strategy';
export async function loadCatalog(): Promise<Catalog> { return (await apiClient.get(path)).data; }
export async function selectStrategy(env: Environment, strategy: string) { await apiClient.put(path + '/' + env, { strategy }); }
export const usdt = (value: number | null) => value == null ? '—' : Number(value).toFixed(2) + ' USDT';
