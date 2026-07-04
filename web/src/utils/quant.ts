export function formatScore(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

export function formatPredictedReturn(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}%`;
}

export const regimeLabels: Record<string, string> = { risk_on: '适合承担风险', neutral: '中性', risk_off: '降低风险' };
export const actionLabels: Record<string, string> = { buy:'买入',increase:'增持',hold:'持有',reduce:'减持',sell:'退出',watch:'关注',blocked:'已否决' };
