import apiClient from './index';
import camelcaseKeys from 'camelcase-keys';

export type Market = 'CN' | 'US';
export interface Strategy {
  key: string; version: string; name: string; markets: Market[]; family: string;
  slots: number; atr: number; accountDd: number; cooldown: number; riskEngine: string;
  breadth: boolean; breakout: boolean; sourceId: string; rules: { label: string; text: string }[];
}
export interface Candidate { code: string; name: string; score: number; atr: number; type: string; signalClose: number }
export interface Plan {
  signalDate: string; executionDate: string; status: 'READY' | 'PAUSED';
  candidates: Candidate[]; exits: Record<string, string[]>;
}
export interface Position {
  name: string; quantity: number; entryPrice: number; mark: number; markDate: string;
  peak: number; stop: number | null; pendingExit: string[];
}
export interface Fill {
  code: string; name: string; action: 'BUY' | 'SELL'; quantity: number; price: number;
  amount: number; pnl: number | null; reasons: string[]; signalDate: string;
}
export interface Metrics {
  tradeDate: string; nav: number; dailyReturn: number; totalReturn: number; cagr: number | null;
  maxDrawdown: number; drawdown: number; exposure: number; benchmarkReturn: number | null;
}
export interface Day extends Metrics {
  createdAt: string;
  payload: {
    cash: number; positions: Record<string, Position>; fills: Fill[];
    adjustments: { code: string; scale: number; reason: string }[];
    blocked: { code: string; action: string; reason: string }[];
    plan: Plan; warnings: string[]; staleCodes: string[]; sessions: number; closedRounds: number;
    winRate: number | null; annualTurnover: number; pauseRemaining: number;
    breadth: number | null; breadthDenominator: number | null; provenance: Record<string, unknown>;
    computedAt: string; replayed: boolean; nextIsHistorical: boolean;
  };
}
export interface Run { tradeDate: string; status: 'success' | 'waiting' | 'failed'; reason: string | null; attempts: number; updatedAt: string }
export interface Item {
  strategy: Strategy; latest: Day | null; lastRun: Run | null; startDate: string | null;
  status: 'success' | 'waiting' | 'failed' | 'not_started' | 'catching_up';
}
export interface Overview { expectedDate?: string; market: Market; items: Item[] }
export interface Detail {
  expectedDate?: string; market: Market; strategy: Strategy; latest: Day | null; lastRun: Run | null; startDate: string | null;
  universe: { stocks: string[]; etfs: string[]; breadth: string[]; hash: string } | null;
  curve: Metrics[]; days: Day[]; nextBefore: string | null;
}
export function adapt<T>(data: unknown): T {
  // Canonical security identifiers are dictionary keys, not field names.
  return camelcaseKeys(data as Record<string, unknown>, { deep: true, exclude: [/\.(?:US|SH|SZ|BJ)$/] }) as T;
}
const base = '/api/v1/stock-strategies';
export const stockStrategiesApi = {
  async overview(market: Market): Promise<Overview> { return adapt((await apiClient.get(base, { params: { market } })).data); },
  async detail(key: string, market: Market, before?: string): Promise<Detail> {
    return adapt((await apiClient.get(`${base}/${encodeURIComponent(key)}`, { params: { market, before, limit: 50 } })).data);
  },
  async run(market: Market, strategyKey?: string): Promise<{ taskId: string }> {
    return adapt((await apiClient.post(`${base}/run`, { market, strategy_key: strategyKey })).data);
  },
};
