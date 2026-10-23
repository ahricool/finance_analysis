import { describe, expect, it } from 'vitest';
import type { HeatmapStock } from '@/api/marketHeatmap';
import { areaWeights, changeColor, heatmapTree } from '../display';

const stock = (i: number, cap = 2e9): HeatmapStock => ({ code: `${i}.US`, name: `Stock ${i}`, marketCap: cap,
  price: 10, changePct: 1, groupCode: 'tech', groupName: '科技', quoteTime: null });
describe('market heatmap area and colors', () => {
  it('compresses concentration, caps a giant at 3%, and preserves real capitalization', () => {
    const rows = Array.from({ length: 100 }, (_, i) => stock(i, i === 0 ? 5e12 : 2e9));
    const weights = areaWeights(rows);
    expect(weights.reduce((a, b) => a + b, 0)).toBeCloseTo(1);
    expect(Math.max(...weights)).toBeCloseTo(0.03);
    expect(weights[0]).toBeGreaterThan(weights[1]!);
    const tree = heatmapTree(rows);
    expect(tree).toHaveLength(1);
    expect(tree[0]!.children[0]).toMatchObject({ stock: { marketCap: 5e12 } });
  });
  it('handles sparse pools and gives each stock one leaf', () => {
    expect(areaWeights([])).toEqual([]);
    expect(areaWeights([stock(0)])).toEqual([1]);
    const tree = heatmapTree([stock(0), { ...stock(1), groupCode: 'banks', groupName: '银行' }]);
    expect(tree).toHaveLength(2);
    expect(tree.reduce((sum, row) => sum + row.children.length, 0)).toBe(2);
  });
  it('uses red for gains, green for losses and distinct gray for missing data', () => {
    expect(changeColor(5)).toBe('#e0273d');
    expect(changeColor(-5)).toBe('#126644');
    expect(changeColor(null)).not.toBe(changeColor(0));
  });
});
