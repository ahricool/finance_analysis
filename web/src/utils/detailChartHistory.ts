// Display metadata only: never add Preview rows to the official detail history.
export type DetailChartPoint<T> = T & { isPreview?: boolean };

export function detailChartHistory<T extends { tradeDate: string }>(
  history: T[], latest: T, preview: boolean,
): DetailChartPoint<T>[] {
  if (!preview) return history;
  return [
    ...history.filter(row => row.tradeDate < latest.tradeDate).map(row => ({ ...row, isPreview: false })),
    { ...latest, isPreview: true },
  ].sort((a, b) => a.tradeDate.localeCompare(b.tradeDate));
}

export function chartDate(row: DetailChartPoint<{ tradeDate: string }>): string {
  return `${row.tradeDate}${row.isPreview ? ' · Preview' : ''}`;
}
