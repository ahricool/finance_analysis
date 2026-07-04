import type { BacktestEngineKey, BacktestMarket, BacktestStatus } from '@/types/backtests';

export const marketLabels: Record<BacktestMarket, string> = { US: '美股', CN: 'A股', HK: '港股' };
export const engineLabels: Record<BacktestEngineKey, string> = {
  backtrader: 'Backtrader',
  rqalpha: 'RQAlpha',
};
export const statusLabels: Record<BacktestStatus, string> = {
  pending: '等待中',
  processing: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export function formatPct(value?: number | null): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(2)}%`;
}

export function formatMoney(value?: number | null): string {
  return value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
}
