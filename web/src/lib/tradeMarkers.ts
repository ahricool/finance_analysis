export type TradeMarkerType = 'B' | 'S' | 'T';

export interface TradeMarkerOperation {
  executedAt: string;
  side: 'BUY' | 'SELL' | string;
  quantity?: string;
  price?: string;
  label?: string;
}

export interface TradeMarker {
  timestamp: number;
  type: TradeMarkerType;
  operations: TradeMarkerOperation[];
  strategyKey?: string;
  strategyName?: string;
}

export function markerLabel(type: TradeMarkerType) {
  return type;
}

export function bucketOperations(
  operations: Array<{ executedAt: number; side: string; quantity?: string; price?: string; label?: string }>,
  buckets: Array<{ start: number; end: number }>,
): TradeMarker[] {
  const grouped = new Map<number, TradeMarkerOperation[]>();
  for (const item of operations) {
    const bucket = buckets.find(row => row.start < item.executedAt && item.executedAt <= row.end);
    if (!bucket) continue;
    const list = grouped.get(bucket.start) ?? [];
    list.push({
      executedAt: new Date(item.executedAt).toISOString(),
      side: item.side,
      quantity: item.quantity,
      price: item.price,
      label: item.label,
    });
    grouped.set(bucket.start, list);
  }
  return [...grouped.entries()].map(([timestamp, rows]) => {
    const sides = new Set(rows.map(row => row.side === 'EXIT' ? 'SELL' : row.side));
    const buy = sides.has('BUY');
    const sell = sides.has('SELL');
    const type: TradeMarkerType = buy && sell ? 'T' : buy ? 'B' : 'S';
    return { timestamp, type, operations: rows };
  });
}
