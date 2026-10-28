import type { Candidate, Day, Detail, Position, Strategy } from '@/api/stockStrategies';

export const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
export function positionMetrics(pos: Position, nav: number | undefined) {
  const valid = finite(pos.quantity) && pos.quantity > 0 && finite(pos.mark) && pos.mark > 0;
  const value = valid ? pos.quantity * pos.mark : null;
  const cost = finite(pos.entryPrice) && pos.entryPrice > 0 && finite(pos.quantity) && pos.quantity > 0
    ? pos.quantity * pos.entryPrice : null;
  const pnl = value != null && cost != null ? value - cost : null;
  return { value, weight: value != null && finite(nav) && nav > 0 ? value / nav : null,
    pnl, pnlPct: pnl != null && cost != null && cost > 0 ? pnl / cost : null,
    stopDistance: valid && finite(pos.stop) && pos.stop > 0 ? (pos.mark - pos.stop) / pos.mark : null };
}
export function runStatus(detail: Detail) {
  if (detail.lastRun?.status && detail.lastRun.status !== 'success') return detail.lastRun.status;
  if (detail.latest && detail.expectedDate && detail.latest.tradeDate < detail.expectedDate) return 'catching_up';
  return detail.latest ? 'success' : 'not_started';
}
export const families: Record<string, string> = { ma: '均线趋势', ma_market: '均线与市场开关', momentum: '动量轮动',
  regression: '回归趋势', hybrid: '股票 / ETF混合', trend_quality: '趋势质量' };
export function strategyTags(s: Strategy) {
  return [families[s.family] ?? s.family, `最多${s.slots}仓`, s.atr ? `ATR ${s.atr}` : '无ATR',
    s.accountDd ? `账户回撤${s.accountDd * 100}% / 暂停${s.cooldown}个开盘` : '', s.breadth ? '广度开关' : ''].filter(Boolean).join(' · ');
}
export function scoreLabel(s: Strategy, c: Candidate) {
  if (s.family === 'ma' || s.family === 'ma_market') return 'MA20/MA50−1';
  if (s.family === 'momentum') return '60日收益';
  if (s.family === 'regression') return '年化对数斜率 × R²';
  if (s.family === 'trend_quality' || (s.family === 'hybrid' && c.type !== 'ETF')) return 'Trend60';
  if (s.family === 'hybrid') return '126日动量 / max(波动率, 0.10)';
  return '本策略评分';
}
export function exitRows(day: Day | null | undefined) {
  const exits: Record<string, string[]> = {};
  for (const [code, pos] of Object.entries(day?.payload.positions ?? {})) {
    const reasons = [...new Set([...pos.pendingExit, ...(day?.payload.plan?.exits[code] ?? [])])];
    if (reasons.length) exits[code] = reasons;
  }
  return Object.entries(exits);
}
