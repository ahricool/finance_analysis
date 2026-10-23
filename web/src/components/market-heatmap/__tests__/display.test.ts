import { describe, expect, it } from 'vitest';
import type { HeatmapStock } from '@/api/marketHeatmap';
import { areaWeights, changeColor, colorScale, filterStocks, heatmapGroups } from '../display';

const stock = (i: number, cap = 2e9): HeatmapStock => ({ code: `${i}.US`, name: `Stock ${i}`, marketCap: cap,
  price: 10, changePct: 1, groupCode: 'tech', groupName: '科技', quoteTime: null });
describe('market heatmap area and colors', () => {
  it('increases capitalization contrast, bounds tile size, and preserves real capitalization', () => {
    const rows = Array.from({ length: 100 }, (_, i) => stock(i, i === 0 ? 5e12 : 2e9));
    const weights = areaWeights(rows);
    expect(weights.reduce((a, b) => a + b, 0)).toBeCloseTo(1);
    expect(weights[0]).toBeGreaterThan(weights[1]!);
    const tree = heatmapGroups(rows, 5);
    expect(tree).toHaveLength(1);
    expect(tree[0]!.tiles[0]).toMatchObject({ stock: { marketCap: 5e12 }, columnSpan: 3, rowSpan: 3 });
    expect(tree[0]!.tiles.at(-1)).toMatchObject({ columnSpan: 1, rowSpan: 1 });
    const varied = Array.from({ length: 1000 }, (_, i) => stock(i, i === 0 ? 2e11 : 2e9));
    const contrast = areaWeights(varied);
    expect(contrast[0]! / contrast[1]!).toBeGreaterThan(Math.sqrt(100));
  });
  it('handles sparse pools and gives each stock one leaf', () => {
    expect(areaWeights([])).toEqual([]);
    expect(areaWeights([stock(0)])).toEqual([1]);
    const tree = heatmapGroups([stock(0), { ...stock(1), groupCode: 'banks', groupName: '银行' }], 2);
    expect(tree).toHaveLength(2);
    expect(tree.reduce((sum, row) => sum + row.tiles.length, 0)).toBe(2);
    expect(tree.every(group => group.tiles.every(tile => tile.columnSpan <= 2 && tile.rowSpan <= 2))).toBe(true);
  });
  it('filters name, canonical code and industry while preserving a stock size', () => {
    const rows = [stock(0, 5e12), stock(1), { ...stock(2), groupCode: 'banks', groupName: '银行' }];
    const all = heatmapGroups(rows, 5);
    const filtered = heatmapGroups(rows, 5, 'stock 0');
    expect(filtered[0]!.tiles[0]).toEqual(all[0]!.tiles[0]);
    expect(filterStocks(rows, '  1.US  ').map(row => row.code)).toEqual(['1.US']);
    expect(filterStocks(rows, '', 'banks').map(row => row.code)).toEqual(['2.US']);
    expect(heatmapGroups(rows, 5, 'missing')).toEqual([]);
  });
  it('uses red for gains, green for losses and distinct gray for missing data', () => {
    expect(changeColor(5)).toBe('#e0273d');
    expect(changeColor(-5)).toBe('#126644');
    expect(changeColor(null)).not.toBe(changeColor(0));
  });
  it('keeps white stock labels readable across every heatmap color', () => {
    for (const color of [...colorScale.map(step => step.color), changeColor(null)]) {
      const channels = [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16) / 255)
        .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
      const luminance = channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
      expect(1.05 / (luminance + 0.05)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
