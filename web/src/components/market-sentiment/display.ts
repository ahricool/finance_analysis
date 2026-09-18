export const stateLabels: Record<string, string> = { UNKNOWN: '数据不足', ICE: '冰点', REPAIR: '修复', ACTIVE: '活跃', CLIMAX: '高潮', DIVERGENCE: '分歧', COOLING: '退潮', NEUTRAL: '平稳' };
export const boards = ['1', '2', '3', '4', '5', '6', '7+'];
export const pct = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(1)}%`;
export const money = (n: number | null | undefined) => n == null ? '—' : n >= 1e8 ? `${(n / 1e8).toFixed(2)}亿元` : `${(n / 1e4).toFixed(2)}万元`;
export const flag = (v: boolean | null | undefined) => v == null ? '未知' : v ? '是' : '否';
export const delta = (n: number | null | undefined, percentage = false) => n == null ? '较前日 —' : `较前日 ${n > 0 ? '+' : ''}${(n * (percentage ? 100 : 1)).toFixed(percentage ? 1 : 0)}${percentage ? ' 个百分点' : ''}`;
