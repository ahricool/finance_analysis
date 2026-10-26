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
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface HeatmapGroup {
  code: string;
  name: string;
  marketCap: number;
  totalCount: number;
  height: number;
  tiles: HeatmapTile[];
}

export function filterStocks(items: HeatmapStock[], search = '', group = ''): HeatmapStock[] {
  const needle = search.trim().toLocaleLowerCase();
  return items.filter(stock => (!group || stock.groupCode === group)
    && (!needle || `${stock.name} ${stock.code}`.toLocaleLowerCase().includes(needle)));
}

// Balanced binary treemap: split the longest edge near half the weight.
// A small weight floor prevents a large cap leader turning its peers into slivers.
function layout(stocks: HeatmapStock[], width: number, height: number): HeatmapTile[] {
  const weights = areaWeights(stocks);
  const floor = Math.max(...weights) / 100;
  const entries = stocks.map((stock, i) => ({ stock, weight: Math.max(weights[i]!, floor) }));
  const tiles: HeatmapTile[] = [];
  function split(rows: typeof entries, x: number, y: number, w: number, h: number) {
    if (rows.length === 1) {
      tiles.push({ stock: rows[0]!.stock, x, y, width: w, height: h });
      return;
    }
    const total = rows.reduce((sum, row) => sum + row.weight, 0);
    let left = rows[0]!.weight;
    let cut = 1;
    while (cut < rows.length - 1 && Math.abs(left + rows[cut]!.weight - total / 2) < Math.abs(left - total / 2)) {
      left += rows[cut++]!.weight;
    }
    const fraction = left / total;
    if (w >= h) {
      split(rows.slice(0, cut), x, y, w * fraction, h);
      split(rows.slice(cut), x + w * fraction, y, w * (1 - fraction), h);
    } else {
      split(rows.slice(0, cut), x, y, w, h * fraction);
      split(rows.slice(cut), x, y + h * fraction, w, h * (1 - fraction));
    }
  }
  if (entries.length) split(entries, 0, 0, width, height);
  return tiles;
}

export function heatmapGroups(items: HeatmapStock[], width: number, search = '', selectedGroup = ''): HeatmapGroup[] {
  const panelWidth = Math.max(240, width);
  const groups = new Map<string, HeatmapStock[]>();
  for (const stock of filterStocks(items, search, selectedGroup)) {
    const rows = groups.get(stock.groupCode) ?? [];
    rows.push(stock);
    groups.set(stock.groupCode, rows);
  }
  return [...groups.entries()].map(([code, rows]) => {
    rows.sort((a, b) => b.marketCap - a.marketCap || a.code.localeCompare(b.code));
    const marketCap = rows.reduce((sum, row) => sum + row.marketCap, 0);
    // Keep every stock. Dense sectors grow vertically rather than dropping small cells.
    const height = Math.max(rows.length <= 2 ? 180 : panelWidth < 420 ? 300 : 340,
      Math.ceil(rows.length * 600 / panelWidth));
    const tiles = layout(rows, panelWidth, height);
    return { code, name: rows[0]!.groupName, marketCap, totalCount: rows.length, height, tiles };
  }).sort((a, b) => b.marketCap - a.marketCap || a.code.localeCompare(b.code));
}
