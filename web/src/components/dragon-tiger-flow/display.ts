import type { FlowEvidence, FlowOverview } from '@/api/dragonTigerFlow';
export function money(value: number | null | undefined): string {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${(value / 1e8).toFixed(2)}亿`;
}
export function sumKnown(values: (number | null)[]): number | null {
  return values.some(v => v === null) ? null : values.reduce<number>((s, v) => s + (v ?? 0), 0);
}
export interface FlowStock { symbol: string; name: string; netValue: number | null; rows: FlowEvidence[] }
export function conceptStocks(data: FlowOverview | null, id: string): FlowStock[] {
  const groups = new Map<string, FlowEvidence[]>();
  for (const row of data?.evidence ?? []) {
    if (row.conceptId !== id) continue;
    groups.set(row.symbol, [...(groups.get(row.symbol) ?? []), row]);
  }
  return [...groups].map(([symbol, rows]) => ({ symbol, name: rows[0]!.name,
    netValue: data?.complete ? sumKnown(rows.map(r => r.netValue)) : null, rows,
  })).sort((a, b) => Number(a.netValue === null) - Number(b.netValue === null)
    || (b.netValue ?? 0) - (a.netValue ?? 0) || a.symbol.localeCompare(b.symbol));
}
export function stockEvidence(data: FlowOverview | null, symbol: string): FlowEvidence[] {
  const unique = new Map<string, FlowEvidence>();
  for (const row of data?.evidence ?? []) if (row.symbol === symbol) unique.set(row.tradeDate, row);
  return [...unique.values()].sort((a, b) => a.tradeDate.localeCompare(b.tradeDate));
}
export function signedStocks(stocks: FlowStock[], positive: boolean) {
  const rows = stocks.filter(r => r.netValue !== null && (positive ? r.netValue > 0 : r.netValue < 0))
    .sort((a, b) => Math.abs(b.netValue!) - Math.abs(a.netValue!) || a.symbol.localeCompare(b.symbol));
  const top = rows.slice(0, 5).map(r => ({ name: r.name, symbol: r.symbol, value: r.netValue! }));
  if (rows.length > 5) top.push({ name: '其余股票', symbol: '', value: rows.slice(5).reduce((s, r) => s + r.netValue!, 0) });
  return top;
}
export function exportObservation(data: FlowOverview) {
  // Export exactly the displayed generation, including source/quality, never raw upstream payloads.
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url;
  anchor.download = `dragon-tiger-flow-${data.tradeDate}-${data.board}-${data.rangeDays}d.json`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}


export interface FlowStockSummary {
  symbol: string; name: string; netValue: number | null; observedNetValue: number | null;
  buyValue: number | null; sellValue: number | null; orgNetValue: number | null; hotMoneyNetValue: number | null;
  observedDays: number; concepts: string[];
}
export function allStocks(data: FlowOverview | null): FlowStockSummary[] {
  const groups = new Map<string, FlowEvidence[]>();
  for (const row of data?.evidence ?? []) groups.set(row.symbol, [...(groups.get(row.symbol) ?? []), row]);
  return [...groups].map(([symbol, rows]) => {
    const daily = new Map(rows.map(r => [r.tradeDate, r]));
    const observedNetValue = sumKnown([...daily.values()].map(r => r.originalNetValue));
    // Net is original stock/day evidence; other amounts are summed from all concept allocations once.
    return { symbol, name: rows[0]!.name, netValue: data?.complete ? observedNetValue : null, observedNetValue,
      buyValue: sumKnown(rows.map(r => r.buyValue)), sellValue: sumKnown(rows.map(r => r.sellValue)),
      orgNetValue: sumKnown(rows.map(r => r.orgNetValue)), hotMoneyNetValue: sumKnown(rows.map(r => r.hotMoneyNetValue)),
      observedDays: daily.size, concepts: [...new Set(rows.flatMap(r => r.concepts))],
    };
  });
}
