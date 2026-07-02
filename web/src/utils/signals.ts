import type {
  SignalDirection,
  SignalEvaluation,
  SignalEvaluationItem,
  SignalEvaluationPeriod,
  SignalMarket,
} from '@/types/signals';

export const SIGNAL_PERIODS: SignalEvaluationPeriod[] = ['30m', '1h', '1d', '3d', '7d'];

export const SIGNAL_TYPE_LABELS: Record<string, string> = {
  relative_strength_breakout: '相对强势突破',
  relative_weakness_breakdown: '相对弱势破位',
  weak_to_strong_reversal: '弱转强',
  strong_to_weak_failure: '强转弱',
  near_limit_up_acceleration: '临近涨停加速',
  limit_up_sealed: '涨停封板',
  limit_up_break_open: '涨停开板',
  high_open_low_move: '高开低走',
  abnormal_volume_breakout: '异常放量突破',
  near_limit_down_risk: '临近跌停风险',
  one_word_limit_up: '一字涨停',
};

export const MARKET_LABELS: Record<SignalMarket, string> = {
  CN: 'A股',
  US: '美股',
  HK: '港股',
};

export const DIRECTION_LABELS: Record<SignalDirection, string> = {
  bullish: '看多',
  bearish: '看空',
  sideways: '震荡',
  neutral: '中性',
};

export type EvaluationDisplayState = 'evaluated' | 'pending' | 'not_applicable' | 'invalid';

export function signalTypeLabel(value?: string | null): string {
  const normalized = value?.trim() || '—';
  return SIGNAL_TYPE_LABELS[normalized] ?? normalized;
}

export function directionLabel(value: string): string {
  return DIRECTION_LABELS[value as SignalDirection] ?? (value || '—');
}

export function marketLabel(value: string): string {
  return MARKET_LABELS[value as SignalMarket] ?? (value || '—');
}

export function evaluationState(
  evaluation: SignalEvaluation,
  period: SignalEvaluationPeriod,
): EvaluationDisplayState {
  const item = evaluation[period];
  if (!item) return 'pending';
  if (item.status === 'not_applicable') return 'not_applicable';
  if (typeof item.returnPct === 'number' && Number.isFinite(item.returnPct)) return 'evaluated';
  return 'invalid';
}

export function evaluationStatusLabel(
  evaluation: SignalEvaluation,
  period: SignalEvaluationPeriod,
): string {
  const state = evaluationState(evaluation, period);
  if (state === 'pending') return '待评估';
  if (state === 'not_applicable') return '不适用';
  if (state === 'invalid') return '—';
  return formatReturnPct(evaluation[period]?.returnPct);
}

export function formatReturnPct(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function returnClass(value?: number | null): string {
  if (value !== null && value !== undefined && value > 0) return 'text-red-500';
  if (value !== null && value !== undefined && value < 0) return 'text-emerald-500';
  return 'text-foreground';
}

export function formatSignalPrice(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  }).format(value);
}

export function notApplicableReason(item?: SignalEvaluationItem): string {
  if (item?.reason === 'non_intraday_signal') return '非盘中信号';
  return item?.reason || '—';
}
