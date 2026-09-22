import { describe, it, expect } from 'vitest';
import { toCamelCase } from '@/api/utils';
import type { FlowOverview } from '@/api/dragonTigerFlow';
import raw from '../../../../e2e/fixtures/dragonTigerFlow';
import { allStocks, conceptStocks, signedStocks, stockEvidence, sumKnown } from '../display';
const data = toCamelCase<FlowOverview>(raw);
describe('Dragon Tiger evidence accounting', () => {
  it('conserves selected concept contributions including remaining stocks on both sides', () => {
    const c = data.concepts.find(c => c.name === '半导体')!;
    const stocks = conceptStocks(data, c.id);
    const signed = [...signedStocks(stocks, true), ...signedStocks(stocks, false)];
    expect(signed.some(r => r.name === '其余股票')).toBe(true);
    expect(signed.reduce((s, r) => s + r.value, 0)).toBe(c.netValue);
    expect(stocks[0]!.netValue).toBeGreaterThan(stocks.at(-1)!.netValue!);
  });
  it('deduplicates daily stock facts across concept allocations', () => {
    const rows = stockEvidence(data, '600001.SH');
    expect(rows).toHaveLength(5);
    expect(rows[0]!.originalNetValue).toBe(800000000);
    expect(rows[0]!.netValue).toBe(400000000);
  });
  it('does not synthesize missing totals', () => {
    expect(sumKnown([1, null])).toBeNull();
    expect(conceptStocks({ ...data, complete: false }, data.concepts[0]!.id).every(s => s.netValue === null)).toBe(true);
    expect(sumKnown([])).toBe(0);
  });
});


it('shows all stock-level evidence without double-counting concept allocations', () => {
  const rows = allStocks(data);
  expect(rows).toHaveLength(data.summary.stockCount);
  const row = rows.find(r => r.symbol === '600001.SH')!;
  expect(row.netValue).toBe(4000000000);
  expect(row.observedDays).toBe(5);
  expect(row.buyValue).toBe(6000000000);
  const partial = allStocks({ ...data, complete: false }).find(r => r.symbol === '600001.SH')!;
  expect(partial.netValue).toBeNull();
  expect(partial.observedNetValue).toBe(row.netValue);
  const unknown = allStocks({ ...data, evidence: data.evidence.map(r => ({ ...r, hotMoneyNetValue: null })) });
  expect(unknown.every(r => r.hotMoneyNetValue === null)).toBe(true);
});
