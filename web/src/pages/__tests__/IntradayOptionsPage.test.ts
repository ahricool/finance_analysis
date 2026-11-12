import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import IntradayOptionsPage from '../market/IntradayOptionsPage.vue';
import type { IntradayOptionRow, IntradayOptionsSnapshot } from '@/api/intradayOptions';
import { fetchIntradayOptions } from '@/api/intradayOptions';

vi.mock('@/api/intradayOptions', () => ({ fetchIntradayOptions: vi.fn() }));
let page: VueWrapper;
let data: IntradayOptionsSnapshot;
function row(symbol: string, score: number | null, direction: 'bullish' | 'bearish' = 'bullish'): IntradayOptionRow {
  return { symbol, name: `${symbol}名称`, lastPrice: score, changePct: score == null ? null : score / 10,
    quoteTime: new Date().toISOString(), quoteStatus: 'ready', dataStatus: score == null ? 'warming' : 'ready', issues: [],
    result: { version: 'v1', symbol, tradingDate: '2026-11-12', asOf: new Date().toISOString(), observedAt: new Date().toISOString(),
      score, direction: score == null ? null : direction, state: score == null ? null : 'continuing', baseScore: score,
      alignment: 1, extensionAtr: 1, explanation: '趋势一致', windows: ([5, 15, 30, 60] as const).map(minutes => ({
        minutes, score, direction: direction === 'bullish' ? 1 : -1, dataStatus: score == null ? 'warming' : 'ready',
        returnPct: 0.5, reasons: [], startAt: null, endAt: null, stability: null, efficiency: null,
        strength: null, disturbance: null, normalizedMove: null, adverseMove: null, adverseDuration: null,
        movementGate: null, concentration: null, stalledImpulse: false,
      })) } };
}
async function start() {
  page = mount(IntradayOptionsPage, { global: { stubs: { TrendPanel: true, MetricHint: true } } });
  await flushPromises();
}
function symbols() { return page.findAll('[data-testid^="options-row-"]').map(r => r.attributes('data-testid')!.replace('options-row-', '')); }
async function header(label: string) { await page.findAll('thead button').find(b => b.text().startsWith(label))!.trigger('click'); }
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-12T16:00:05Z'));
  data = { tradingDate: '2026-11-12', marketStatus: 'open', generatedAt: new Date().toISOString(), version: 'v1',
    items: [row('AAA.US', 70), row('BBB.US', 90, 'bearish'), row('CCC.US', null)] };
  vi.mocked(fetchIntradayOptions).mockImplementation(async () => structuredClone(data));
});
afterEach(() => { page?.unmount(); vi.useRealTimers(); vi.clearAllMocks(); });

describe('intraday options table', () => {
  it('defaults to opportunity order and sorts all numeric headers with nulls always last', async () => {
    await start();
    expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    for (const label of ['最新价', '当日涨跌幅', '5分钟', '15分钟', '30分钟', '60分钟', '趋势机会分']) {
      await header(label); expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
      await header(label); expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    }
    expect(page.findAll('thead th[aria-sort="descending"]')).toHaveLength(1);
    await header('标的'); expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
    await header('当前方向'); expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    await header('当前状态'); expect(symbols().at(-1)).toBe('CCC.US');
  });

  it('updates cells without jumping rows or closing the expanded chart; explicitly refreshes order', async () => {
    await start();
    await page.get('[data-testid="options-row-AAA.US"]').trigger('click');
    expect(page.find('trend-panel-stub').exists()).toBe(true);
    data.items[0]!.result!.score = 99;
    data.generatedAt = new Date().toISOString();
    await vi.advanceTimersByTimeAsync(5000); await flushPromises();
    expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    expect(page.get('[data-testid="options-row-AAA.US"]').text()).toContain('99');
    expect(page.find('trend-panel-stub').exists()).toBe(true);
    await page.get('[data-testid="options-refresh-order"]').trigger('click');
    expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
  });

  it('filters by direction and searches names; retains annotated scores on failed refresh and cancels on unmount', async () => {
    await start();
    await page.findAll('button').find(b => b.text() === '偏空')!.trigger('click');
    expect(symbols()).toEqual(['BBB.US']);
    await page.get('input').setValue('AAA'); expect(symbols()).toEqual([]);
    await page.get('input').setValue('名称'); expect(symbols()).toEqual(['BBB.US']);
    vi.mocked(fetchIntradayOptions).mockRejectedValueOnce(new Error('offline'));
    await vi.advanceTimersByTimeAsync(5000); await flushPromises();
    expect(page.get('[data-testid="opportunity-score"]').text()).toContain('90');
    expect(page.text()).toContain('保留上次评分');
    const calls = vi.mocked(fetchIntradayOptions).mock.calls.length;
    page.unmount(); await vi.advanceTimersByTimeAsync(10000);
    expect(fetchIntradayOptions).toHaveBeenCalledTimes(calls);
  });
  it('shows and sorts delayed scores with missing-minute annotations', async () => {
    const target = data.items[1]!;
    target.dataStatus = 'delayed';
    target.result!.windows[0]!.dataStatus = 'gap';
    target.result!.windows[0]!.missingBars = 1;
    target.result!.windows[0]!.availableBars = 14;
    await start();
    const displayed = page.get(`[data-testid="options-row-${target.symbol}"]`);
    expect(displayed.text()).toContain('分钟行情延迟');
    expect(displayed.text()).toContain('缺1根 · 参考分');
    expect(displayed.text()).toContain('参考分 · 截至');
    expect(displayed.get('[data-testid="opportunity-score"]').text()).toContain(String(target.result!.score));
    expect(symbols()[0]).toBe(target.symbol);
  });

});
