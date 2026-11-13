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
    for (const label of ['最新价 / 涨跌幅', '5分钟', '15分钟', '30分钟', '60分钟', '趋势机会分']) {
      await header(label); expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
      await header(label); expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    }
    expect(page.findAll('thead th[aria-sort="descending"]')).toHaveLength(1);
    await header('标的'); expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
    await header('当前方向'); expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
    await header('当前状态'); expect(symbols().at(-1)).toBe('CCC.US');
  });

  it('merges price and change, sorts by change rather than price and keeps the requested column order', async () => {
    data.items[0]!.lastPrice = 500;
    data.items[0]!.changePct = -2;
    data.items[1]!.lastPrice = 10;
    data.items[1]!.changePct = 3;
    await start();
    expect(page.findAll('thead th button').map(b => b.text())).toEqual([
      '标的', '最新价 / 涨跌幅', '趋势机会分', '当前方向', '5分钟', '15分钟', '30分钟', '60分钟', '短线结构', '当前状态',
    ]);
    const cells = page.get('[data-testid="options-row-AAA.US"]').findAll('td');
    expect(cells).toHaveLength(10);
    expect(cells[1]!.text()).toContain('500.00');
    expect(cells[1]!.text()).toContain('-2.00%');
    await header('最新价 / 涨跌幅'); expect(symbols()).toEqual(['AAA.US', 'BBB.US', 'CCC.US']);
    await header('最新价 / 涨跌幅'); expect(symbols()).toEqual(['BBB.US', 'AAA.US', 'CCC.US']);
  });

  it('displays opening reference scores, direction and missing counts before a full window', async () => {
    const target = data.items[0]!;
    target.dataStatus = 'warming';
    for (const w of target.result!.windows) {
      w.dataStatus = 'warming'; w.availableBars = 2; w.missingBars = w.minutes - 2;
    }
    await start();
    const displayed = page.get('[data-testid="options-row-AAA.US"]');
    expect(displayed.text()).toContain('开盘不足');
    expect(displayed.text()).toContain('缺58根 · 参考分');
    expect(displayed.text()).toContain('偏多');
    expect(displayed.get('[data-testid="opportunity-score"]').text()).toContain('70');
    expect(displayed.get('[data-testid="opportunity-score"]').text()).toContain('参考分');
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

  it('places sortable structure after 60m and annotates reference and delayed results', async () => {
    const target = data.items[0]!;
    target.dataStatus = 'delayed';
    target.result!.structure = { kind: 'breakout_up', phase: 'confirmed', background: 'bearish',
      since: '2026-11-12T16:00:00Z', asOf: '2026-11-12T16:00:00Z', oversold: false, reference: true,
      availableBars: 59, missingBars: 1, box: null, pivots: [], reasons: ['固定箱体突破'] };
    await start();
    const headers = page.findAll('thead th').map(h => h.text());
    expect(headers.findIndex(h => h.includes('短线结构'))).toBe(headers.findIndex(h => h.includes('60分钟')) + 1);
    const cell = page.get('[data-testid="options-row-AAA.US"] [data-testid="intraday-structure"]');
    expect(cell.text()).toContain('箱体向上突破');
    expect(cell.text()).toContain('已确认 · 偏空背景');
    expect(cell.text()).toContain('参考结构 · 缺1根');
    expect(cell.text()).toContain('延迟 · 截至');
    await header('短线结构');
    expect(symbols()[0]).toBe('AAA.US');
    await header('短线结构');
    expect(symbols()[0]).toBe('AAA.US');
  });

  it('shows a short pause without changing the independent opportunity state', async () => {
    data.items[0]!.result!.structure = { kind: 'uptrend', phase: 'pausing', background: 'bullish',
      since: '2026-11-12T16:00:00Z', asOf: '2026-11-12T16:00:00Z', oversold: false, reference: false,
      availableBars: 60, missingBars: 0, box: null, pivots: [], reasons: ['最近5分钟缺乏有效推进'] };
    await start();
    const displayed = page.get('[data-testid="options-row-AAA.US"]');
    expect(displayed.get('[data-testid="intraday-structure"]').text()).toContain('持续走强');
    expect(displayed.get('[data-testid="intraday-structure"]').text()).toContain('短线停顿');
    expect(displayed.findAll('td').at(-1)!.text()).toBe('趋势持续');
  });

});
