export const outlookStatus: Record<string, string> = {
  current: '当前前瞻', frozen: '公布前预测', stale: '预测已过期', superseded: '事件已变更，待重新分析',
  ineligible: '不在当前覆盖范围', pending: '待分析', processing: '分析中', failed: '分析失败，待重试',
};
export const searchStatus: Record<string, string> = {
  confirmed: '已确认搜索执行', unverified: '搜索执行未能确认', unavailable: '搜索不可用', not_requested: '未请求搜索',
};
export const guidanceLabels: Record<string, string> = { above: '高于预期', inline: '符合预期', below: '低于预期', unknown: 'unknown' };
export const scenarioLabels: Record<string, string> = { optimistic: '乐观', base: '基准', pessimistic: '悲观' };
export function price(value: number | null | undefined) { return value == null ? '—' : `$${value.toFixed(2)}`; }
export function pct(value: number | null | undefined) { return value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`; }
