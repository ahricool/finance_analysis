import type { MacroRegime, MacroTrend } from '@/api/macro';
import { enumLabel } from '@/i18n/labels';
import { formatPercent } from '@/utils/quant';

export const macroAssets = ['SPY', 'QQQ', 'TLT', 'UUP', 'USO', 'GLD', 'HYG', 'LQD', 'IWM', 'SMH', 'XLY', 'XLP', 'VIX'].map(s => `${s}.US`);
export const defaultAssets = ['SPY.US', 'QQQ.US', 'TLT.US', 'UUP.US', 'USO.US', 'HYG.US'];
export const ratioDescriptions: Record<string, string> = {
  HYG_LQD: 'Credit Risk Appetite', IWM_SPY: 'Small Cap Breadth',
  SMH_SPY: 'Semiconductor Leadership', XLY_XLP: 'Cyclical / Defensive',
};
export const ratioKeys = Object.keys(ratioDescriptions);
export const seriesLabel = (key: string) => key.replace(/\.US/g, '').replaceAll('_', ' / ');

/** Plain Chinese for places that cannot mount BilingualEnum (tests / selects). */
export const regimeLabel = (value: MacroRegime | null) => value === null ? '数据不足' : enumLabel(value).zh;
export const trendLabel = (value: MacroTrend | null) => {
  if (value === null) return '—';
  const pair = enumLabel(value);
  const arrow = value === 'UP' ? '↑ ' : value === 'DOWN' ? '↓ ' : '→ ';
  return `${arrow}${pair.zh}`;
};
export const returnClass = (value: number | null) => value === null || value === 0 ? 'text-muted-foreground' : value > 0 ? 'text-market-up' : 'text-market-down';
export const returnLabel = (value: number | null) => `${value !== null && value > 0 ? '+' : ''}${formatPercent(value, 2)}`;
export const numberLabel = (value: number | null, digits = 2) => value === null ? '—' : value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
