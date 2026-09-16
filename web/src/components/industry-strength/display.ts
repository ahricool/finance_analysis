import type { IndustryState } from '@/api/industryStrength';
export const stateLabels: Record<IndustryState, string> = { EMERGING: '加速崛起', STRONG: '持续强势', NEUTRAL: '中性', COOLING: '降温', WEAK: '弱势' };
export const stateColors: Record<IndustryState, string> = { EMERGING: '#d97706', STRONG: '#e5484d', NEUTRAL: '#64748b', COOLING: '#0891b2', WEAK: '#16866d' };
export function pct(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(2)}%`; }
export function num(value: number | null | undefined) { return value == null ? '—' : value.toFixed(1); }
export function delta(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
export function tone(value: number | null) { return value == null || value === 0 ? 'text-muted-foreground' : value > 0 ? 'text-market-up' : 'text-market-down'; }
