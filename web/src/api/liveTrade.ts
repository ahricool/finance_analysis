import apiClient from './index';
import type { Row } from './paperTrade';

export interface LiveControl { enabled: boolean; updated_at: string | null }
export interface LiveSnapshot {
  environment: 'LIVE';
  control: LiveControl;
  connection: { status: string; stream_connected: boolean; reason?: string | null };
  view: { account: Row; balances: Row[]; positions: Row[]; open_orders: Row[]; open_algos: Row[];
    complete: boolean; synced_at: string } | null;
  equity: { time: string; equity: string | null }[];
  orders: Row[];
  algos: Row[];
  trades: Row[];
  income: Row[];
  realized_net: string | null;
  control_events: Row[];
  strategy_count: number;
}
const path = '/api/v1/crypto/live-trade';
export const liveTradeApi = {
  async snapshot(): Promise<LiveSnapshot> { return (await apiClient.get(path)).data; },
  async control(): Promise<LiveControl> { return (await apiClient.get(path + '/control')).data; },
  async setControl(enabled: boolean): Promise<LiveControl> { return (await apiClient.put(path + '/control', { enabled })).data; },
};
