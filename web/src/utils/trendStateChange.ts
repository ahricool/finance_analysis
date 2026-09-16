import type { TrendState } from '@/types/trendFollowing';

const STATE_CHANGE_LABELS: Array<{ from: readonly TrendState[]; to: TrendState; label: string }> = [
  { from: ['CANDIDATE'], to: 'TRENDING', label: '新确认趋势' },
  { from: ['WEAKENING'], to: 'TRENDING', label: '趋势恢复' },
  { from: ['IDLE', 'WATCHING'], to: 'CANDIDATE', label: '新进入趋势候选' },
  { from: ['BROKEN'], to: 'CANDIDATE', label: '重新形成趋势候选' },
  { from: ['TRENDING'], to: 'WEAKENING', label: '趋势开始弱化' },
  { from: ['TRENDING', 'WEAKENING', 'CANDIDATE'], to: 'BROKEN', label: '趋势破坏' },
  { from: ['CANDIDATE'], to: 'WEAKENING', label: '候选弱化' },
];

export function describeTrendStateChange(previous: TrendState, current: TrendState): string {
  return STATE_CHANGE_LABELS.find(item => item.to === current && item.from.includes(previous))?.label ?? '状态变化';
}

export const TREND_TRANSITION_RANGES = [
  { days: 1, label: '今日变化' },
  { days: 3, label: '近3个快照' },
  { days: 5, label: '近5个快照' },
] as const;
