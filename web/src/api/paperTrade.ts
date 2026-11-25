import apiClient from './index';

export type Row = Record<string, unknown>;
export interface PaperView {
  account: Row;
  positions: Row[];
  open_orders?: Row[];
  open_algos?: Row[];
  shared_symbols?: string[];
  demo_symbols?: string[];
  synced_at: string;
  complete: boolean;
}
export interface DemoTradeControl { enabled: boolean; updated_at: string | null }
export interface PaperSnapshot {
  trade_control: DemoTradeControl;
  connection: { status: string; stream_connected: boolean; reason?: string | null };
  view: PaperView | null;
  equity: { time: string; equity: string | null }[];
  strategies: Row[];
  intents: Row[];
  orders: Row[];
  algos: Row[];
  trades: Row[];
  income: Row[];
  realized_net: string | null;
}
const path = '/api/v1/crypto/paper-trade';
export const paperTradeApi = {
  async snapshot(): Promise<PaperSnapshot> { return (await apiClient.get(path)).data; },
  async tradeControl(): Promise<DemoTradeControl> { return (await apiClient.get(path + '/control')).data; },
  async setTradeControl(enabled: boolean): Promise<DemoTradeControl> { return (await apiClient.put(path + '/control', { enabled })).data; },
  async saveStrategy(symbol: string, payload: Row) { return (await apiClient.put(path + '/strategies/' + encodeURIComponent(symbol), payload)).data; },
  async control(symbol: string, enabled: boolean) { return (await apiClient.post(path + '/strategies/' + encodeURIComponent(symbol) + '/control', { enabled })).data; },
  async action(type: 'orders' | 'close' | 'cancel', payload: Row) { return (await apiClient.post(path + '/' + type, payload)).data; },
};
