export interface OpportunityBranch {
  backgroundPeriods: number[]; structureId: string; kind: string; ruleVersion: string; status: string; qualityScore: number | null;
  trigger: number; support: number; invalidation: number; distancePct: number; distanceAtr: number;
  firstConfirmedAt: string | null; discoveredAt: string; startDate: string; endDate: string;
  dataAsOf: string; anchorDate: string; anchorClose: number; preview: boolean; fresh: boolean;
  trendBackground?: Record<string, unknown>; evidence?: Record<string, unknown>; reason: string; unmet: string[]; points: Array<{ date: string; price: number; knownDate: string }>;
}
export interface OpportunityItem {
  code: string; name: string; primary: OpportunityBranch | null; display: OpportunityBranch | null;
  branches: OpportunityBranch[]; historyStatus: string; dataAsOf: string;
}
export interface OpportunityResponse {
  items: OpportunityItem[]; generatedAt: string | null; tradeDate: string; status: string;
  scannedCount: number; coveredCount: number; candidateCount: number; candidateLimit: number;
}
export const patternNames: Record<string, string> = {
  breakout: '普通突破', ma5: 'MA5 浅回踩', ma10: 'MA10 回踩', retest: '突破位回测',
  box_retest: '箱顶回测', flat_base: '平底突破', box: '箱体突破', vcp: 'VCP 收缩', cup_handle: '杯柄突破',
};
export const opportunityStates: Record<string, string> = {
  CONFIRMED: '有效买点', NEAR_TRIGGER: '接近触发', FORMING: '形成中', EXTENDED: '已延伸',
  INVALIDATED: '已失效', PULLING_BACK: '回踩中', WAITING_PULLBACK: '等待回踩',
};
export const opportunityColumns = [
  ['name', '证券'], ['kind', '主结构'], ['status', '当前状态'], ['qualityScore', '分支质量'],
  ['trigger', '触发价'], ['distancePct', '距触发位'], ['distanceAtr', 'ATR 距离'],
  ['invalidation', '结构失效参考'], ['firstConfirmedAt', '首次确认'],
] as const;
export type OpportunitySort = typeof opportunityColumns[number][0];
export function opportunityValue(item: OpportunityItem, key: OpportunitySort): string | number | null {
  const b = item.primary ?? item.display;
  return key === 'name' ? item.name : b?.[key] ?? null;
}
export function filterOpportunities(items: OpportunityItem[], state: string, kind: string, search: string,
  sort: OpportunitySort | null, direction: 'asc' | 'desc') {
  const query = search.trim().toLowerCase();
  const result = items.filter(item => (!query || `${item.code} ${item.name}`.toLowerCase().includes(query))
    && (!kind || item.branches.some(b => b.kind === kind))
    && (!state || (state === 'FRESH' ? item.branches.some(b => b.fresh) : item.branches.some(b => b.status === state))));
  if (sort) result.sort((a, b) => {
    const av = opportunityValue(a, sort), bv = opportunityValue(b, sort);
    if (av == null || bv == null) return av == null ? bv == null ? a.code.localeCompare(b.code) : 1 : -1;
    const delta = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv));
    return delta ? delta * (direction === 'asc' ? 1 : -1) : a.code.localeCompare(b.code);
  });
  return result;
}
