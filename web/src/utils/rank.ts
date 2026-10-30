/** Position within the original ranked cohort, never the filtered/displayed subset. */
export function rankPercentage(rank: unknown, total: unknown): number | null {
  if (typeof rank !== 'number' || !Number.isInteger(rank) || rank < 1
    || typeof total !== 'number' || !Number.isInteger(total) || total < rank) return null;
  return rank / total * 100;
}

export function formatRank(rank: unknown, total?: unknown): string {
  if (typeof rank !== 'number' || !Number.isInteger(rank) || rank < 1) return '—';
  const percentage = rankPercentage(rank, total);
  if (percentage === null) return `#${rank} · 百分比暂无`;
  const text = percentage < 0.01 ? '<0.01' : String(Number(percentage.toFixed(2)));
  return `#${rank} · 前 ${text}%`;
}
