/** Build the same lossless table envelope as the research list APIs. */
export function compactTrendResponse(path: string, body: object): object {
  if (!path.includes('/trend-following/') || !(/\/ranking(?:\/table)?$/.test(path))) return body;
  const data = body as Record<string, unknown>;
  const items = (data.snapshots ?? data.items ?? []) as Record<string, unknown>[];
  const columns = [...new Set(items.flatMap(row => Object.keys(row).filter(key =>
    key !== 'features' && (row[key] == null || ['string', 'number', 'boolean'].includes(typeof row[key])))))];
  const features = [...new Set(items.flatMap(row => Object.keys(row.features as object ?? {})))];
  return { ...data, items: undefined, snapshots: undefined, table: {
    columns, feature_columns: features,
    rows: items.map(row => [...columns.map(key => row[key] ?? null),
      ...features.map(key => (row.features as Record<string, unknown> | undefined)?.[key] ?? null)]),
  } };
}
export function isRankingPath(path: string) { return /\/ranking(?:\/table)?$/.test(path); }
