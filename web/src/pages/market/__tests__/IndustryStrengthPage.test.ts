import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import { createPinia } from 'pinia';
import type { Constituent, IndustrySnapshot } from '@/api/industryStrength';
import { toCamelCase } from '@/api/utils';
import IndustryStrengthPage from '../IndustryStrengthPage.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import IndustryMatrixChart from '@/components/industry-strength/IndustryMatrixChart.vue';
import IndustryRankHeatmap from '@/components/industry-strength/IndustryRankHeatmap.vue';
import IndustryRankingTable from '@/components/industry-strength/IndustryRankingTable.vue';

const api = vi.hoisted(() => ({ ranking: vi.fn(), dates: vi.fn(), history: vi.fn(), detail: vi.fn(), constituents: vi.fn() }));
vi.mock('@/api/industryStrength', () => ({ industryStrengthApi: api }));
vi.mock('vue-echarts', () => ({ default: { template: '<div data-testid="chart" />' } }));

function row(code = '881101.TI', name = '行业甲', rank = 1, overrides: Partial<IndustrySnapshot> = {}): IndustrySnapshot {
  return {
    tradeDate: '2026-09-16', industryCode: code, industryName: name, state: rank === 1 ? 'STRONG' : 'NEUTRAL', close: 100,
    strengthRank: rank, strengthScore: 90 - rank, ret1D: rank === 1 ? 0.01 : -0.01, ret5D: 0.03, ret10D: 0.04, ret20D: 0.05,
    rs5D: 0.01, rs10D: 0.02, rs20D: 0.03, rankChange1D: rank === 1 ? 2 : 0, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: 0.01, momentumAcceleration5D: rank === 1 ? 0.02 : -0.03, accelerationPercentile: 80, turnoverRatio5D: 1.2,
    upRatio: 0.7, aboveMa5Ratio: 0.8, aboveMa20Ratio: 0.9, equalWeightReturn: 0.01,
    constituentCount: 10, dailyValidCount: 10, ma5ValidCount: 10, aboveMa5Count: 8, ma20ValidCount: 10, aboveMa20Count: 9,
    upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: '2026-09-16T07:00:00Z', membersObservedAt: '2026-09-16T11:00:00Z',
    createdAt: '2026-09-16T11:05:00Z', updatedAt: '2026-09-16T11:05:00Z',
    quality: { dailyBreadthCoverage: 1, ma5Coverage: 1, ma20Coverage: 1, catalogCount: 2, rankedCount: 2, coverage: 1, excluded: {} },
    ...overrides,
  };
}

const rows = [row(), row('881102.TI', '行业乙', 2)];

let wrapper: VueWrapper | undefined;

async function render(query = '') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/research/industry-strength', component: IndustryStrengthPage }] });
  await router.push('/research/industry-strength' + query);
  await router.isReady();
  wrapper = mount(IndustryStrengthPage, {
    attachTo: document.body,
    global: { plugins: [router, createPinia()] },
  });
  return wrapper;
}

function detailEl() {
  return document.body.querySelector('[data-testid="industry-detail-dialog"]');
}

function detailText() {
  return detailEl()?.textContent ?? '';
}

async function closeDialog() {
  const close = document.body.querySelector('[data-testid="industry-detail-close"]') as HTMLButtonElement | null;
  close?.click();
  await flushPromises();
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  document.body.replaceChildren();
});

beforeEach(() => {
  vi.clearAllMocks();
  api.ranking.mockResolvedValue({ tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: rows });
  api.dates.mockResolvedValue(['2026-09-16', '2026-09-15']);
  api.history.mockResolvedValue({ dates: ['2026-09-16'], items: rows });
  api.detail.mockImplementation(async (code: string) => ({ current: rows.find(r => r.industryCode === code), history: rows.filter(r => r.industryCode === code) }));
  api.constituents.mockImplementation(async (code: string) => ({
    industryCode: code, updatedAt: '2026-09-17T11:00:00Z',
    constituentCount: 0, dailyValidCount: 0, ma5ValidCount: 0, aboveMa5Count: 0, ma20ValidCount: 0, aboveMa20Count: 0, items: [],
  }));
});

describe('Industry Strength', () => {
  const memberRows: Constituent[] = [
    { code: '003.SH', name: 'A', trendRank: 2, price: 20, changePct: .1, aboveMa5: true, aboveMa20: false, amount: 30, volume: 1 },
    { code: '002.SH', name: 'B', trendRank: 1, price: 10, changePct: .3, aboveMa5: false, aboveMa20: true, amount: 10, volume: 1 },
    { code: '005.SH', name: 'D', trendRank: null, price: null, changePct: null, aboveMa5: null, aboveMa20: null, amount: null, volume: null },
    { code: '001.SH', name: 'A', trendRank: 1, price: 10, changePct: .3, aboveMa5: false, aboveMa20: true, amount: 10, volume: 1 },
    { code: '004.SH', name: 'C', trendRank: null, price: null, changePct: null, aboveMa5: null, aboveMa20: null, amount: null, volume: null },
  ];
  const ascending = ['001.SH', '002.SH', '003.SH', '004.SH', '005.SH'];
  const descending = ['003.SH', '001.SH', '002.SH', '004.SH', '005.SH'];
  it.each([
    ['股票', ['001.SH', '003.SH', '002.SH', '004.SH', '005.SH'], ['005.SH', '004.SH', '002.SH', '001.SH', '003.SH']],
    ['Trend Rank', ascending, descending],
    ['收盘价', descending, ascending],
    ['涨跌幅（%）', descending, ascending],
    ['MA5', descending, ascending],
    ['MA20', ascending, descending],
    ['成交额', descending, ascending],
  ])('sorts %s in both directions locally with stable ties and nulls last', async (label, first, second) => {
    const items = Object.freeze(memberRows.map(item => Object.freeze({ ...item })));
    api.constituents.mockResolvedValueOnce({ industryCode: '881101.TI', updatedAt: '2026-09-17T11:00:00Z',
      constituentCount: 5, dailyValidCount: 3, ma5ValidCount: 3, ma20ValidCount: 3, items });
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-summary-strongest"]').trigger('click'); await flushPromises();
    const section = detailEl()!.querySelector('[data-testid="industry-detail-constituents"]')!;
    const codes = () => [...section.querySelectorAll('tbody tr')].map(row => row.querySelector('td span')!.textContent);
    expect(codes()).toEqual(ascending); // Initial changePct DESC, even when API items are unsorted.
    expect(section.querySelector('thead [aria-sort="descending"]')?.textContent).toContain('涨跌幅');
    const nullRow = [...section.querySelectorAll('tbody tr')].find(row => row.textContent?.includes('004.SH'))!;
    expect(nullRow.querySelectorAll('td')[1]!.textContent?.trim()).toBe('—');
    expect(section.textContent).toContain('当前成分股（最新数据）');
    expect(section.textContent).toContain('不随上方历史快照日期变化');
    expect(section.textContent).toContain('不对应上方历史日期');
    const header = [...section.querySelectorAll('thead button')].find(button => button.textContent?.trim() === label)!;
    for (const expected of [first, second]) {
      (header as HTMLButtonElement).click(); await flushPromises();
      expect(codes()).toEqual(expected);
    }
    expect(api.constituents).toHaveBeenCalledTimes(1);
    expect(api.detail).toHaveBeenCalledTimes(1);
    expect(items).toEqual(memberRows);
  });

  it('renders loading then rankings without auto-opening the dialog', async () => {
    let resolve!: (value: unknown) => void;
    api.ranking.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = await render();
    expect(wrapper.find('[data-testid="industry-loading"]').exists()).toBe(true);
    resolve({ tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: rows });
    await flushPromises();
    expect(wrapper.find('[data-testid="industry-ranking"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="industry-trade-date"]').text()).toContain('2026-09-16');
    expect(wrapper.get('[data-testid="industry-summary"]').text()).toContain('最强行业');
    expect(wrapper.get('[data-testid="industry-summary"]').text()).toContain('动量降速最大');
    expect(wrapper.get('[data-testid="industry-summary-advancing"]').text()).toContain('50.0%（1 / 2）');
    expect(document.body.querySelector('[data-testid="industry-detail-dialog"]')).toBeNull();
    expect(api.detail).not.toHaveBeenCalled();
    expect(api.constituents).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="industry-ranking"]').text()).toContain('70.0');
    expect(wrapper.get('[data-testid="industry-ranking"]').text()).toContain('↑2 名');
    wrapper.unmount();
  });

  it('opens the same dialog from ranking, summary and both charts', async () => {
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-summary-strongest"]').trigger('click'); await flushPromises();
    expect(detailText()).toContain('行业甲');
    expect(api.detail).toHaveBeenLastCalledWith('881101.TI', '2026-09-16');
    expect(api.constituents).toHaveBeenLastCalledWith('881101.TI');
    expect(detailEl()?.getAttribute('role')).toBe('dialog');
    expect(detailEl()?.querySelector('[role="tablist"]')).toBeNull();
    for (const section of ['overview', 'history', 'constituents']) {
      expect(detailEl()?.querySelector(`[data-testid="industry-detail-${section}"]`)).not.toBeNull();
    }
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises();
    expect(detailText()).toContain('行业乙');
    await wrapper.getComponent(IndustryMatrixChart).vm.$emit('select', '881101.TI'); await flushPromises();
    expect(detailText()).toContain('行业甲');
    await wrapper.getComponent(IndustryRankHeatmap).vm.$emit('select', '881102.TI'); await flushPromises();
    expect(detailText()).toContain('行业乙');
    expect(api.constituents).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it('keeps sort, filter and scroll context after closing the dialog', async () => {
    const wrapper = await render(); await flushPromises();
    const table = wrapper.getComponent(IndustryRankingTable);
    await wrapper.get('[data-testid="industry-search"]').setValue('行业乙');
    await table.findAll('button').find(b => b.text().includes('排名'))!.trigger('click');
    const scroller = table.vm.scroller;
    if (scroller) scroller.scrollTop = 48;
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises();
    expect(detailText()).toContain('行业乙');
    await closeDialog();
    expect(detailEl()).toBeNull();
    expect(wrapper.get('[data-testid="industry-search"]').element).toHaveProperty('value', '行业乙');
    expect(wrapper.get('[data-testid="industry-filter-count"]').text()).toContain('当前显示 1 / 全部 2 个行业');
    expect(table.vm.sortKey).toBe('strengthRank');
    expect(table.vm.descending).toBe(true);
    expect(table.vm.scroller).toBe(scroller);
    expect(table.vm.scroller?.scrollTop).toBe(scroller?.scrollTop);
    wrapper.unmount();
  });

  it('does not change original ranks or summary when filtering or switching columns', async () => {
    const wrapper = await render(); await flushPromises();
    const summary = wrapper.get('[data-testid="industry-summary"]').text();
    await wrapper.get('[data-testid="industry-search"]').setValue('行业乙');
    expect(wrapper.get('[data-testid="industry-ranking"]').text()).toContain('2');
    expect(wrapper.get('[data-testid="industry-ranking"]').text()).not.toContain('行业甲');
    expect(wrapper.get('[data-testid="industry-summary"]').text()).toBe(summary);
    await wrapper.get('[data-testid="industry-clear-filters"]').trigger('click');
    await wrapper.get('[data-testid="industry-column-mode"]').findAll('button').find(b => b.text() === '完整指标')!.trigger('click');
    expect(wrapper.get('[data-testid="industry-ranking"]').text()).toContain('3 日变化');
    expect(wrapper.get('[data-testid="industry-summary"]').text()).toBe(summary);
    wrapper.unmount();
  });

  it('renders explicit empty state without requesting live constituents', async () => {
    api.ranking.mockResolvedValue({ items: [], tradeDate: null });
    const wrapper = await render(); await flushPromises();
    expect(wrapper.find('[data-testid="industry-empty"]').exists()).toBe(true);
    expect(api.constituents).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows API failure and retry', async () => {
    api.ranking.mockRejectedValue(new Error('offline'));
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).toContain('重新加载');
    expect(wrapper.find('[data-testid="industry-ranking"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('automatically loads constituents and isolates that failure from details', async () => {
    api.constituents.mockRejectedValue(new Error('upstream unavailable'));
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业甲')!.trigger('click');
    await flushPromises();
    expect(detailText()).toContain('行业甲');
    await flushPromises();
    expect(api.constituents).toHaveBeenCalledTimes(1);
    expect(detailText()).toContain('重试当前成分');
    expect(detailText()).toContain('行业甲');
    expect(detailEl()?.querySelector('[data-testid="industry-detail-history"] tbody')).not.toBeNull();
    api.constituents.mockResolvedValueOnce({ industryCode: '881101.TI', updatedAt: '2026-09-18T11:00:00Z', items: [] });
    const retry = [...detailEl()!.querySelectorAll('button')].find(button => button.textContent?.includes('重试当前成分'))!;
    retry.click();
    await flushPromises();
    expect(api.constituents).toHaveBeenCalledTimes(2);
    expect(detailText()).not.toContain('重试当前成分');
    expect(detailText()).toContain('2026/09/18');
    wrapper.unmount();
  });

  it('ignores stale detail responses after changing industry', async () => {
    let resolve!: (value: unknown) => void;
    api.detail.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业甲')!.trigger('click');
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises();
    resolve({ current: rows[0], history: [rows[0]] });
    await flushPromises();
    expect(detailText()).toContain('行业乙');
    expect(detailText()).not.toContain('强度排名 1行业甲');
    wrapper.unmount();
  });

  it('keeps partial industries ranked and renders missing breadth as a dash', async () => {
    api.ranking.mockResolvedValue({
      tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: [
        { ...row(), aboveMa20Ratio: null, ma20ValidCount: 6, aboveMa20Count: 5, quality: { ...row().quality, ma20Coverage: 0.6 } },
      ],
    });
    const wrapper = await render(); await flushPromises();
    const table = wrapper.get('[data-testid="industry-ranking"]');
    expect(table.text()).toContain('行业甲');
    expect(table.text()).toContain('—');
    expect(table.text()).not.toContain('持平—');
    expect(table.text()).toContain('覆盖不足');
    wrapper.unmount();
  });

  it('does not offer a manual refresh button', async () => {
    const wrapper = await render(); await flushPromises();
    expect(wrapper.find('[data-testid="industry-refresh"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('does not attach a failed date change to the previous snapshot', async () => {
    const wrapper = await render(); await flushPromises();
    api.ranking.mockRejectedValueOnce(new Error('offline'));
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-15');
    await flushPromises();
    expect(wrapper.get('[data-testid="industry-date-pending"]').text()).toContain('2026-09-15');
    expect(wrapper.get('[data-testid="industry-trade-date"]').text()).toContain('2026-09-16');
    wrapper.unmount();
  });

  it('refreshes an open dialog and reports a missing industry instead of switching', async () => {
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises();
    api.ranking.mockResolvedValueOnce({ tradeDate: '2026-09-15', expectedTradeDate: '2026-09-16', items: [row('881101.TI', '行业甲', 1)] });
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-15');
    await flushPromises();
    expect(detailText()).toContain('不在 2026-09-15 截面中');
    expect(detailText()).toContain('行业乙');
    wrapper.unmount();
  });

  it('isolates history failures from the ranking table', async () => {
    api.history.mockRejectedValue(new Error('history unavailable'));
    const wrapper = await render(); await flushPromises();
    expect(wrapper.find('[data-testid="industry-ranking"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('重试排名历史');
    wrapper.unmount();
  });

  it('loads the selected snapshot date and can return to latest', async () => {
    const wrapper = await render(); await flushPromises();
    const picker = wrapper.getComponent(AppDatePicker);
    expect(picker.props('availableDates')).toEqual(['2026-09-16', '2026-09-15']);
    expect(picker.props('placeholder')).toContain('2026-09-16');
    api.ranking.mockResolvedValueOnce({ tradeDate: '2026-09-15', expectedTradeDate: '2026-09-16', items: rows });
    picker.vm.$emit('update:modelValue', '2026-09-15'); await flushPromises();
    expect(api.ranking).toHaveBeenLastCalledWith('2026-09-15');
    expect(api.detail).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="industry-go-latest"]').exists()).toBe(true);
    await wrapper.get('[data-testid="industry-go-latest"]').trigger('click'); await flushPromises();
    expect(api.ranking).toHaveBeenLastCalledWith(undefined);
    wrapper.unmount();
  });

  it('keeps constituent dates isolated from the selected snapshot', async () => {
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业甲')!.trigger('click');
    await flushPromises();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="industry-constituents-dates"]')?.textContent).toContain('2026/09/17');
    expect(document.body.querySelector('[data-testid="industry-constituents-banner"]')?.textContent).toContain('不随上方历史快照日期变化');
    expect(detailText()).toContain('实际查询快照日期 2026-09-16');
    wrapper.unmount();
  });

  it('labels index-only historical backfill without treating zero coverage as 覆盖不足', async () => {
    api.ranking.mockResolvedValueOnce({
      tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: [
        {
          ...row(),
          upRatio: null,
          aboveMa5Ratio: null,
          aboveMa20Ratio: null,
          quality: {
            ...row().quality,
            breadthStatus: 'unavailable_historical_members',
            dailyBreadthCoverage: 0,
            ma5Coverage: 0,
            ma20Coverage: 0,
          },
        },
      ],
    });
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).toContain('缺少当日成分记录，历史广度不可用');
    expect(wrapper.text()).not.toContain('覆盖不足');
    expect(wrapper.text()).not.toContain('对应广度比例显示为不可用');
    wrapper.unmount();
  });

  it('keeps numeric window casing in API conversion', () => {
    expect(toCamelCase({ rs_5d: .1, ret_10d: .2, above_ma5_ratio: .6, rank_change_3d: 1 }))
      .toEqual({ rs5D: .1, ret10D: .2, aboveMa5Ratio: .6, rankChange3D: 1 });
  });

  it('does not show industry A metrics under industry B while B detail is pending', async () => {
    api.detail.mockImplementation(async (code: string) => ({
      current: rows.find(r => r.industryCode === code),
      history: [{ ...rows.find(r => r.industryCode === code)!, tradeDate: '2026-08-01', strengthScore: 12.34 }],
    }));
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业甲')!.trigger('click');
    await flushPromises();
    await flushPromises();
    expect(detailText()).toContain('2026-08-01');
    let resolveB!: (value: unknown) => void;
    api.detail.mockReturnValueOnce(new Promise(r => { resolveB = r; }));
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises();
    expect(detailText()).toContain('行业乙');
    expect(detailText()).not.toContain('2026-08-01');
    expect(detailText()).toContain('强度排名 2');
    expect(detailText()).toContain('正在加载历史表现');
    resolveB({ current: rows[1], history: [{ ...rows[1], tradeDate: '2026-08-02' }] });
    await flushPromises();
    expect(detailText()).toContain('行业乙');
    expect(detailText()).not.toContain('2026-08-01');
    wrapper.unmount();
  });

  it('does not keep T detail history after a failed T-1 detail request', async () => {
    api.detail.mockImplementation(async (code: string, tradeDate?: string) => ({
      current: { ...rows.find(r => r.industryCode === code)!, tradeDate: tradeDate ?? '2026-09-16' },
      history: [{ ...rows[0], tradeDate: '2026-08-01', strengthScore: 12.34 }],
    }));
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业甲')!.trigger('click');
    await flushPromises();
    await flushPromises();
    expect(detailText()).toContain('2026-08-01');
    api.ranking.mockResolvedValueOnce({
      tradeDate: '2026-09-15', expectedTradeDate: '2026-09-16',
      items: rows.map(item => ({ ...item, tradeDate: '2026-09-15' })),
    });
    api.history.mockResolvedValueOnce({ dates: ['2026-09-15'], items: [] });
    api.detail.mockRejectedValueOnce(new Error('detail offline'));
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-15');
    await flushPromises();
    expect(wrapper.get('[data-testid="industry-trade-date"]').text()).toContain('2026-09-15');
    expect(detailText()).toContain('实际查询快照日期 2026-09-15');
    expect(detailText()).not.toContain('2026-08-01');
    wrapper.unmount();
  });

  it('does not paint T history onto the T-1 heatmap', async () => {
    const wrapper = await render(); await flushPromises();
    expect(wrapper.getComponent(IndustryRankHeatmap).props('history').dates).toEqual(['2026-09-16']);
    let resolveHistory!: (reason?: unknown) => void;
    api.ranking.mockResolvedValueOnce({
      tradeDate: '2026-09-15', expectedTradeDate: '2026-09-16',
      items: rows.map(item => ({ ...item, tradeDate: '2026-09-15' })),
    });
    api.history.mockReturnValueOnce(new Promise((_, reject) => { resolveHistory = reject; }));
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-15');
    await flushPromises();
    expect(wrapper.find('[data-testid="industry-history-loading"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="industry-heatmap"]').exists()).toBe(false);
    resolveHistory(new Error('history offline'));
    await flushPromises();
    expect(wrapper.find('[data-testid="industry-heatmap-empty"]').exists()).toBe(true);
    expect(wrapper.getComponent(IndustryRankHeatmap).props('history').dates).toEqual([]);
    wrapper.unmount();
  });

  it('does not show 覆盖不足 for 96% partial coverage', async () => {
    api.ranking.mockResolvedValue({
      tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: [
        { ...row(), quality: { ...row().quality, dailyBreadthCoverage: 0.96, ma5Coverage: 0.96, ma20Coverage: 0.96, breadthStatus: 'partial' } },
      ],
    });
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).not.toContain('覆盖不足');
    expect(wrapper.text()).not.toContain('对应广度比例显示为不可用');
    wrapper.unmount();
  });

  it('still shows 覆盖不足 for an official snapshot below the 0.95 breadth threshold', async () => {
    api.ranking.mockResolvedValue({
      tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: [
        { ...row(), quality: { ...row().quality, dailyBreadthCoverage: 0.94, ma5Coverage: 1, ma20Coverage: 1 } },
      ],
    });
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).toContain('覆盖不足');
    expect(wrapper.text()).toContain('对应广度比例显示为不可用');
    wrapper.unmount();
  });

  it('labels advancing ratio from valid ranked industries and avoids complete-cross-section copy', async () => {
    const wrapper = await render(); await flushPromises();
    expect(wrapper.get('[data-testid="industry-summary-advancing"]').text()).toContain('有效行业上涨占比');
    expect(wrapper.get('[data-testid="industry-summary-advancing"]').text()).toContain('50.0%（1 / 2）');
    expect(wrapper.text()).not.toContain('完整截面');
    wrapper.unmount();
  });
});

it('opens the industry source at the linked official date', async () => {
  await render('?industry=881101.TI&tradeDate=2026-09-16');
  await flushPromises();
  expect(api.ranking).toHaveBeenCalledWith('2026-09-16');
  expect(api.detail).toHaveBeenCalledWith('881101.TI', '2026-09-16');
  expect(detailText()).toContain('行业甲');
});
