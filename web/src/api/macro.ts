import apiClient from './index';
import { toCamelCase } from './utils';

export type MacroTrend = 'UP' | 'DOWN' | 'NEUTRAL';
export type MacroRegime = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
export type MacroRange = '20d' | '60d' | '120d' | '250d' | 'ytd';
export type MacroMode = 'normalized' | 'price' | 'relative';
export interface MacroDataQuality {
  expected: number; available: number; coverage: number; missingSymbols: string[];
  staleSymbols: string[]; insufficientHistorySymbols: string[]; partial: boolean;
}
export interface MacroMetrics {
  tradeDate: string | null; ret1D: number | null; ret5D: number | null;
  ret20D: number | null; trend: MacroTrend | null;
}
export interface MacroInstrument extends MacroMetrics {
  code: string; name: string; category: string; close: number | null;
}
export interface MacroRatio extends MacroMetrics {
  key: string; name: string; value: number | null; signal: MacroRegime | null; partial: boolean;
}
export interface MacroSignal {
  key: string; riskOnTrend: MacroTrend; trend: MacroTrend | null; weight: number; contribution: number | null;
}
export interface MacroStates {
  rates: 'EASING' | 'PRESSURE' | 'NEUTRAL' | null;
  credit: 'HEALTHY' | 'WEAK' | 'NEUTRAL' | null;
  dollar: 'STRONG' | 'WEAK' | 'NEUTRAL' | null;
  volatility: 'ELEVATED' | 'CALM' | 'NEUTRAL' | null;
}
export interface MacroDashboard {
  tradeDate: string | null; generatedAt: string; regime: MacroRegime | null;
  riskScore: number | null; signalCoverage: number; signals: MacroSignal[];
  states: MacroStates; instruments: MacroInstrument[]; ratios: MacroRatio[]; dataQuality: MacroDataQuality;
}
export interface MacroSeries {
  key: string; code: string | null; name: string; category: string;
  points: { date: string; value: number }[]; partial: boolean;
}
export interface MacroSeriesResult {
  range: MacroRange; mode: MacroMode; benchmark: string | null; tradeDate: string | null;
  series: MacroSeries[]; dataQuality: MacroDataQuality;
}
export interface MacroSeriesParams {
  range?: MacroRange; mode?: MacroMode; symbols?: string[]; series?: string[]; benchmark?: string; asOf?: string;
}
export async function getMacroDashboard(params: { asOf?: string } = {}): Promise<MacroDashboard> {
  const { data } = await apiClient.get('/api/v1/macro/dashboard', { params: { as_of: params.asOf } });
  return toCamelCase(data);
}
export async function getMacroSeries(params: MacroSeriesParams = {}): Promise<MacroSeriesResult> {
  const { asOf, symbols, series, ...rest } = params;
  const { data } = await apiClient.get('/api/v1/macro/series', {
    params: { ...rest, as_of: asOf, symbols: symbols?.join(','), series: series?.join(',') },
  });
  return toCamelCase(data);
}
