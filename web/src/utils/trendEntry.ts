import type { TrendFeatures, TrendRankingFeatures } from '@/types/trendFollowing';

export const entryBranches = [
  { key: 'breakout', label: '突破', score: 'entryBreakoutScore', status: 'entryBreakoutStatus', reason: 'entryBreakoutReason' },
  { key: 'ma5', label: 'MA5 浅回踩', score: 'entryMa5Score', status: 'entryMa5Status', reason: 'entryMa5Reason' },
  { key: 'ma10', label: 'MA10 回踩', score: 'entryMa10Score', status: 'entryMa10Status', reason: 'entryMa10Reason' },
  { key: 'retest', label: '突破位回测', score: 'entryRetestScore', status: 'entryRetestStatus', reason: 'entryRetestReason' },
] as const;
export const entryStatusText = (value: unknown, kind?: string) => kind === 'breakout' && value === 'PULLING_BACK' ? '等待确认'
  : kind === 'breakout' && value === 'WAITING_PULLBACK' ? '等待突破' : ({
  WAITING_PULLBACK: '等待回踩', PULLING_BACK: '回踩中', CONFIRMED: '已确认', EXTENDED: '已延伸', INVALIDATED: '已失效',
} as Record<string, string>)[String(value)] ?? '—';
export const entryTypeText = (value: unknown) => ({
  BREAKOUT: '突破', PULLBACK_RESUME: '回踩恢复', BREAKOUT_AND_PULLBACK: '突破 + 回踩', NONE: '尚未确认',
} as Record<string, string>)[String(value)] ?? '—';
export const entryStatusPriority = (value: unknown): number | null => {
  const states = ['CONFIRMED', 'PULLING_BACK', 'WAITING_PULLBACK', 'EXTENDED', 'INVALIDATED'];
  const index = states.indexOf(String(value));
  return index < 0 ? null : index;
};
export function entryBranchForColumn(key: string) {
  return entryBranches.find(branch => branch.status === key);
}
export function entryTextFeature(features: TrendFeatures | TrendRankingFeatures, key: string): string | null {
  const value = (features as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : null;
}
