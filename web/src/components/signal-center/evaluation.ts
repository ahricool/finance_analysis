import type { SignalEvaluation } from '@/api/signalCenter';
import { formatRealizedReturn } from '@/utils/quant';

export function horizonText(evaluation: SignalEvaluation | undefined, days: number): string {
  if (!evaluation || evaluation.status === 'not_applicable') return '—';
  const point = evaluation.horizons.find(h => h.days === days);
  if (!point) return '不可评估';
  if (point.status === 'pending') return '未到期';
  if (point.status === 'missing') return '缺行情';
  return formatRealizedReturn(point.value);
}
export function returnClass(value: number | null | undefined): string {
  return value == null || value === 0 ? '' : value > 0 ? 'text-market-up' : 'text-market-down';
}
