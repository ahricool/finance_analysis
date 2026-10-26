import { describe, expect, it } from 'vitest';
import type { HeatmapStock } from '@/api/marketHeatmap';
import { areaWeights, changeColor, colorScale, filterStocks, heatmapGroups } from '../display';

const stock = (i: number, cap = 2e9): HeatmapStock => ({ code: `${i}.US`, name: `Stock ${i}`, marketCap: cap,
  price: 10, changePct: 1, groupCode: 'tech', groupName: '科技', quoteTime: null });
describe('market heatmap area and colors', () => {
  it('keeps all stocks including the long tail as individual tiles', () => {
    const rows = Array.from({ length: 100 }, (_, i) => stock(i, i === 0 ? 5e12 : 2e9));
    const group = heatmapGroups(rows, 600)[0]!;
    expect(group.totalCount).toBe(100);
    expect(group.tiles).toHaveLength(100);
    expect(group.tiles[0]!.stock.marketCap).toBe(5e12);
    expect(group.marketCap).toBe(5e12 + 99 * 2e9);
    expect(group.tiles.some(tile => tile.width < 72 || tile.height < 72)).toBe(true);
  });
  it('keeps all rectangles non-overlapping and inside the panel across widths', () => {
    const rows = Array.from({ length: 100 }, (_, i) => stock(i, 5e12 / (i + 1)));
    for (const width of [280, 350, 500, 700, 1200]) {
      const group = heatmapGroups(rows, width)[0]!;
      expect(group.tiles).toHaveLength(rows.length);
      let area = 0;
      for (const tile of group.tiles) {
        expect(tile.width).toBeGreaterThan(2);
        expect(tile.height).toBeGreaterThan(2);
        expect(tile.x + tile.width).toBeLessThanOrEqual(width + 0.001);
        expect(tile.y + tile.height).toBeLessThanOrEqual(group.height + 0.001);
        area += tile.width * tile.height;
        for (const other of group.tiles) {
          if (tile === other) continue;
          const overlapX = Math.min(tile.x + tile.width, other.x + other.width) - Math.max(tile.x, other.x);
          const overlapY = Math.min(tile.y + tile.height, other.y + other.height) - Math.max(tile.y, other.y);
          expect(Math.min(overlapX, overlapY)).toBeLessThan(0.001);
        }
      }
      expect(area).toBeCloseTo(width * group.height);
    }
  });
  it('searches the whole snapshot and filters industries', () => {
    const rows = Array.from({ length: 40 }, (_, i) => stock(i, 2e12 / (i + 1)));
    expect(heatmapGroups(rows, 600)[0]!.tiles.some(t => t.stock.code === '39.US')).toBe(true);
    expect(heatmapGroups(rows, 600, '39.US')[0]!.tiles.map(t => t.stock.code)).toEqual(['39.US']);
    expect(filterStocks(rows, '  1.US  ').map(row => row.code)).toEqual(['1.US', '11.US', '21.US', '31.US']);
    expect(heatmapGroups(rows, 600, 'missing')).toEqual([]);
    expect(heatmapGroups(rows, 600, '', 'banks')).toEqual([]);
    expect(heatmapGroups([], 600)).toEqual([]);
    expect(areaWeights([])).toEqual([]);
    expect(areaWeights([stock(0)])).toEqual([1]);
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
