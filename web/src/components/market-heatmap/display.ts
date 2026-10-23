import type { HeatmapStock } from '@/api/marketHeatmap';

export const colorScale = [
  { label: '≤−3%', color: '#126644' }, { label: '−2%', color: '#1e774d' },
  { label: '−1%', color: '#3b7e58' }, { label: '0%', color: '#555b65' },
  { label: '+1%', color: '#b35c62' }, { label: '+2%', color: '#c83c48' },
  { label: '≥+3%', color: '#e0273d' },
];
export function changeColor(change: number | null): string {
  if (change === null) return '#676c75';
  const index = change <= -3 ? 0 : change <= -2 ? 1 : change < -0.05 ? 2 : change < 0.05 ? 3 : change < 2 ? 4 : change < 3 ? 5 : 6;
  return colorScale[index]!.color;
}
export function formatChange(change: number | null): string {
  return change === null ? '涨跌幅暂缺' : `${change > 0 ? '+' : ''}${change.toFixed(2)}%`;
}
export function formatCap(value: number, market: string): string {
  const currency = market === 'CN' ? '元' : '美元';
  return value >= 1e12 ? `${(value / 1e12).toFixed(2)}万亿${currency}` : `${(value / 1e8).toFixed(1)}亿${currency}`;
}

export function areaWeights(items: HeatmapStock[]): number[] {
  if (!items.length) return [];
  const raw = items.map(row => row.marketCap ** 0.75);
  const total = raw.reduce((sum, value) => sum + value, 0);
  return raw.map(value => value / total);
}

export interface HeatmapTile {
  stock: HeatmapStock;
  columnSpan: number;
  rowSpan: number;
  prominent: boolean;
}
export interface HeatmapGroup {
  code: string;
  name: string;
  marketCap: number;
  tiles: HeatmapTile[];
}

export function filterStocks(items: HeatmapStock[], search = '', group = ''): HeatmapStock[] {
  const needle = search.trim().toLocaleLowerCase();
  return items.filter(stock => (!group || stock.groupCode === group)
    && (!needle || `${stock.name} ${stock.code}`.toLocaleLowerCase().includes(needle)));
}

// Reading-sized cells keep all three labels visible. Larger caps occupy several cells.
// Compute sizes from the full snapshot so filtering preserves relative prominence.
export function heatmapGroups(items: HeatmapStock[], columns: number, search = '', selectedGroup = ''): HeatmapGroup[] {
  const count = Math.max(1, Math.floor(columns));
  const weights = areaWeights(items);
  const largest = Math.max(0, ...weights) || 1;
  const visible = new Set(filterStocks(items, search, selectedGroup).map(stock => stock.code));
  const groups = new Map<string, HeatmapGroup>();
  items.forEach((stock, index) => {
    if (!visible.has(stock.code)) return;
    let group = groups.get(stock.groupCode);
    if (!group) {
      group = { code: stock.groupCode, name: stock.groupName, marketCap: 0, tiles: [] };
      groups.set(stock.groupCode, group);
    }
    const cells = 1 + 8 * weights[index]! / largest;
    const [targetColumns, targetRows]: [number, number] = cells >= 8 ? [3, 3] : cells >= 5 ? [3, 2] : cells >= 3 ? [2, 2] : cells >= 1.7 ? [2, 1] : [1, 1];
    const columnSpan = Math.min(count, targetColumns);
    const rowSpan = Math.min(count < 3 ? 2 : 3, Math.ceil(targetColumns * targetRows / columnSpan));
    group.marketCap += stock.marketCap;
    group.tiles.push({ stock, columnSpan, rowSpan, prominent: cells >= 5 });
  });
  for (const group of groups.values()) group.tiles.sort((a, b) => b.stock.marketCap - a.stock.marketCap || a.stock.code.localeCompare(b.stock.code));
  return [...groups.values()].sort((a, b) => b.marketCap - a.marketCap || a.code.localeCompare(b.code));
}
