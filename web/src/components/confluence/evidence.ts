import type { ConfluenceItem, ConfluenceSignal, SignalKey } from '@/api/confluence';
export const primary: SignalKey[] = ['macro', 'etf', 'industry', 'trend'];
export const secondary: SignalKey[] = ['quant', 'options', 'sentiment', 'dragonTiger'];
export const labels: Record<SignalKey, string> = { macro: '宏观环境', etf: '行业 ETF', industry: '行业强度', trend: '趋势追踪', quant: '量化研究', options: '期权情报', sentiment: '市场情绪', dragonTiger: '龙虎榜资金' };
export const weights: Record<SignalKey, number> = { macro: 15, etf: 20, industry: 15, trend: 30, quant: 7, options: 5, sentiment: 4, dragonTiger: 4 };
export const states = { positive: '正向', neutral: '中性', negative: '负向', unavailable: '缺失' };
export function signal(row: ConfluenceItem, key: SignalKey): ConfluenceSignal {
  return row.signals[key] ?? { sourceModule: '', status: 'unavailable', weight: weights[key], score: null, tradeDate: null, sourceGeneratedAt: null, evidence: {}, reasons: ['该版本或日期无对应指标'] };
}
export function strength(row: ConfluenceItem, key: SignalKey): number | null {
  const s = signal(row, key);
  return s.strength ?? (s.score !== null && s.weight ? s.score / s.weight * 100 : null);
}
export function agreement(row: ConfluenceItem): string {
  const available = primary.map(key => signal(row, key)).filter(s => s.status !== 'unavailable');
  return `${available.filter(s => s.status === 'positive').length}/${available.length}`;
}
export function tone(status: string): string {
  return status === 'positive' ? 'text-emerald-600 dark:text-emerald-400' : status === 'negative' ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground';
}
