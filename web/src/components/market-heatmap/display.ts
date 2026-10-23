import type { HeatmapStock } from '@/api/marketHeatmap';

export const colorScale = [
  { label: '≤−3%', color: '#126644' }, { label: '−2%', color: '#238657' },
  { label: '−1%', color: '#4b966b' }, { label: '0%', color: '#555b65' },
  { label: '+1%', color: '#b35c62' }, { label: '+2%', color: '#c83c48' },
  { label: '≥+3%', color: '#e0273d' },
];
export function changeColor(change: number | null): string {
  if (change === null) return '#737780';
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
  const raw = items.map(row => Math.sqrt(row.marketCap));
  const weights = raw.map(() => 0);
  const limit = Math.max(0.03, 1 / items.length);
  let active = raw.map((_, index) => index);
  let remaining = 1;
  while (active.length) {
    const total = active.reduce((sum, index) => sum + raw[index]!, 0);
    const capped = active.filter(index => raw[index]! / total * remaining > limit + 1e-12);
    if (!capped.length) {
      for (const index of active) weights[index] = raw[index]! / total * remaining;
      break;
    }
    for (const index of capped) { weights[index] = limit; remaining -= limit; }
    const frozen = new Set(capped);
    active = active.filter(index => !frozen.has(index));
  }
  return weights;
}

export function heatmapTree(items: HeatmapStock[]) {
  const weights = areaWeights(items);
  const groups = new Map<string, { id: string; name: string; value: number; children: object[] }>();
  items.forEach((stock, index) => {
    let group = groups.get(stock.groupCode);
    if (!group) {
      group = { id: stock.groupCode, name: stock.groupName, value: 0, children: [] };
      groups.set(stock.groupCode, group);
    }
    const value = weights[index]! * 1e6;
    group.value += value;
    group.children.push({ id: stock.code, name: stock.name, value, stock,
      itemStyle: { color: changeColor(stock.changePct) } });
  });
  return [...groups.values()].sort((a, b) => b.value - a.value);
}
