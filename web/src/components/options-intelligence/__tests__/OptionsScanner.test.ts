import { describe, it, expect, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import OptionsIntelligencePage from '@/pages/market/OptionsIntelligencePage.vue';
import { optionsIntelligenceApi, type OptionMetrics, type OptionScore } from '@/api/optionsIntelligence';
vi.mock('@/api/optionsIntelligence', () => ({ optionsIntelligenceApi: { scan: vi.fn() } }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ currentUser: { role: 'user' } }) }));
const mock = vi.mocked(optionsIntelligenceApi.scan);
const stubs = { StockDetailDialog: true, OptionsDataControls: true, FieldSelect: true, PageHeader: true };
const score = (value: number | null): OptionScore => ({ value, method: 'test', evidenceCount: 1, confidence: 'low', reason: null });
const sortableRow = (symbol: string, value: number | null): OptionMetrics => ({
  symbol, status: 'ready', limitations: [],
  underlyingPrice: value, skew30D: value, putCallVolumeRatio: value,
  scores: value == null ? null : { bearishDemand: score(value), unusualActivity: score(value), liquidityRisk: score(value) },
  observedAt: value == null ? undefined : `2026-10-07T${value === 1 ? '10' : '11'}:00:00Z`,
  evidenceGrade: value == null ? undefined : value === 1 ? 'B' : 'A',
});
const rowOrder = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('tbody tr').map(row => row.find('td').text());

describe('Options scanner header sorting', () => {
  it.each([
    ['股价 ($)', 'underlyingPrice'], ['看跌保护需求', 'bearishDemand'], ['异常活动', 'unusualActivity'],
    ['流动性风险', 'liquidityRisk'], ['25Δ Skew', 'skew30D'], ['Put/Call Volume', 'putCallVolumeRatio'], ['更新时间', 'observedAt'],
  ] as const)('toggles %s in both directions with missing values last and stable ties', async (label, key) => {
    const rows = [sortableRow('D.US', null), sortableRow('B.US', null), sortableRow('C.US', null), sortableRow('A.US', null)];
    rows.forEach((row, index) => {
      const value = [null, 0, 2, 0][index]!;
      if (key === 'bearishDemand' || key === 'unusualActivity' || key === 'liquidityRisk') {
        row.scores = { bearishDemand: score(null), unusualActivity: score(null), liquidityRisk: score(null) };
        row.scores[key] = score(value);
      } else if (key === 'observedAt') {
        row.observedAt = value == null ? undefined : `2026-10-07T${value === 0 ? '10' : '11'}:00:00Z`;
      } else row[key] = value;
    });
    mock.mockResolvedValue({ items: rows });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs } });
    await flushPromises();
    expect(rowOrder(wrapper)).toEqual(key === 'unusualActivity' ? ['C.US', 'A.US', 'B.US', 'D.US'] : ['A.US', 'B.US', 'C.US', 'D.US']);
    const header = wrapper.findAll('th').find(th => th.find('[data-slot="bilingual-label"]').text() === label)!;
    if (label !== '异常活动') {
      await header.get('button').trigger('click');
      expect(header.attributes('aria-sort')).toBe('descending');
      expect(rowOrder(wrapper)).toEqual(['C.US', 'A.US', 'B.US', 'D.US']);
    }
    await header.get('button').trigger('click');
    expect(header.attributes('aria-sort')).toBe('ascending');
    expect(rowOrder(wrapper)).toEqual(['A.US', 'B.US', 'C.US', 'D.US']);
    await header.get('button').trigger('click');
    expect(rowOrder(wrapper)).toEqual(['C.US', 'A.US', 'B.US', 'D.US']);
    wrapper.unmount();
  });

  it('orders timestamps by their instant across offsets, with invalid dates last', async () => {
    mock.mockResolvedValue({ items: [
      { ...sortableRow('A.US', null), observedAt: '2026-10-07T12:00:00+02:00' },
      { ...sortableRow('B.US', null), observedAt: '2026-10-07T10:30:00Z' },
      { ...sortableRow('C.US', null), observedAt: 'invalid' },
    ] });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs } });
    await flushPromises();
    const header = wrapper.findAll('th').find(th => th.find('[data-slot="bilingual-label"]').text() === '更新时间')!;
    await header.get('button').trigger('click');
    expect(rowOrder(wrapper)).toEqual(['B.US', 'A.US', 'C.US']);
    await header.get('button').trigger('click');
    expect(rowOrder(wrapper)).toEqual(['A.US', 'B.US', 'C.US']);
    wrapper.unmount();
  });

  it('sorts text columns and keeps the selector and search in sync', async () => {
    mock.mockResolvedValue({ items: [
      sortableRow('D.US', null), sortableRow('B.US', 1),
      { ...sortableRow('C.US', 2), status: 'failed' }, sortableRow('A.US', 1),
    ] });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs } });
    await flushPromises();
    for (const [label, ascending, descending] of [
      ['股票', ['A.US', 'B.US', 'C.US', 'D.US'], ['D.US', 'C.US', 'B.US', 'A.US']],
      ['证据', ['C.US', 'A.US', 'B.US', 'D.US'], ['A.US', 'B.US', 'C.US', 'D.US']],
      ['主要异常', ['C.US', 'A.US', 'B.US', 'D.US'], ['A.US', 'B.US', 'D.US', 'C.US']],
    ] as const) {
      const header = wrapper.findAll('th').find(th => th.find('[data-slot="bilingual-label"]').text() === label)!;
      await header.get('button').trigger('click');
      expect(header.attributes('aria-sort')).toBe('ascending');
      expect(rowOrder(wrapper)).toEqual(ascending);
      await header.get('button').trigger('click');
      expect(header.attributes('aria-sort')).toBe('descending');
      expect(rowOrder(wrapper)).toEqual(descending);
    }
    const selector = wrapper.findAllComponents({ name: 'FieldSelect' }).find(select => select.props('label') === '排序字段')!;
    expect(selector.props('modelValue')).toBe('topEvent');
    selector.vm.$emit('update:modelValue', 'underlyingPrice');
    await flushPromises();
    expect(wrapper.findAll('th').find(th => th.attributes('aria-sort') === 'descending')!.text()).toContain('股价 ($)');
    expect(rowOrder(wrapper)).toEqual(['C.US', 'A.US', 'B.US', 'D.US']);
    await wrapper.get('#options-search').setValue('A.US');
    expect(rowOrder(wrapper)).toEqual(['A.US']);
    wrapper.unmount();
  });
});

describe('Options scanner execution states', () => {
  it('shows official recorded failures with reason and TaskRecord source', async () => {
    mock.mockResolvedValue({ items: [
      { symbol: 'AAPL.US', status: 'failed', scores: null, limitations: ['provider timeout'] },
      { symbol: 'MSFT.US', status: 'not_scanned', scores: null, limitations: [] },
    ], view: 'official', failedCount: 1, latestTaskSummary: { failedCount: 100, totalCount: 100 }, failureSource: 'TaskRecord：所选交易日已记录的逐股结果' });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('采集失败');
    expect(wrapper.text()).toContain('provider timeout');
    expect(wrapper.text()).toContain('已记录采集失败 1 只');
    expect(wrapper.text()).toContain('TaskRecord');
    expect(wrapper.text()).toContain('失败 100 / 计划 100');
    expect(wrapper.text()).toContain('未确认执行结果');
    wrapper.unmount();
  });
  it('labels preserved preview data as an old result after a failed refresh', async () => {
    mock.mockResolvedValue({ items: [{ symbol: 'AAPL.US', status: 'ready', scores: null,
      refreshStatus: 'failed', refreshReason: 'provider unavailable', limitations: [],
      computedAt: '2026-10-07T18:00:00Z' }], failedCount: 1 });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('刷新失败，显示上次预演');
    expect(wrapper.text()).toContain('provider unavailable');
    wrapper.unmount();
  });
});

describe('Options scanner stock names', () => {
  it.each(['official', 'preview'] as const)('shows names and codes in %s rows and the detail entry', async (view) => {
    mock.mockResolvedValue({ items: [
      { symbol: 'NVDA.US', name: 'NVIDIA Corporation', status: 'ready', scores: null, limitations: [] },
      { symbol: 'AAPL.US', name: '苹果', status: 'failed', scores: null, limitations: ['timeout'] },
      { symbol: 'MSFT.US', name: null, status: 'not_scanned', scores: null, limitations: [] },
      { symbol: 'OLD.US', status: 'not_scanned', scores: null, limitations: [] },
    ], view });
    const wrapper = mount(OptionsIntelligencePage, { global: { stubs: {
      ...stubs, PageHeader: { template: '<header><slot name="actions" /></header>' },
    } } });
    await flushPromises();
    if (view === 'preview') {
      wrapper.findComponent({ name: 'OptionsDataControls' }).vm.$emit('update:mode', 'preview');
      await flushPromises();
    }
    expect(mock).toHaveBeenLastCalledWith({ view, tradeDate: undefined });
    expect(wrapper.text()).toContain('NVDA.US - NVIDIA Corporation');
    expect(wrapper.text()).toContain('AAPL.US - 苹果');
    expect(wrapper.text()).toContain('MSFT.US');
    expect(wrapper.text()).toContain('OLD.US');
    expect(wrapper.text()).not.toContain('undefined');
    expect(wrapper.text()).not.toContain('null');

    await wrapper.get('#options-search').setValue('  nViDiA  ');
    expect(wrapper.text()).toContain('NVDA.US - NVIDIA Corporation');
    expect(wrapper.text()).not.toContain('AAPL.US');
    const stockButton = wrapper.findAll('button').find(button => button.text().includes('NVDA.US'))!;
    await stockButton.trigger('click');
    expect(wrapper.findComponent({ name: 'StockDetailDialog' }).props('stock')).toMatchObject({
      code: 'NVDA.US', name: 'NVIDIA Corporation', market_type: 'US',
    });

    await wrapper.get('#options-search').setValue('苹果');
    expect(wrapper.text()).toContain('AAPL.US - 苹果');
    expect(wrapper.text()).not.toContain('NVDA.US');
    await wrapper.get('#options-search').setValue('msft');
    expect(wrapper.text()).toContain('MSFT.US');
    expect(wrapper.text()).not.toContain('AAPL.US');
    await wrapper.findAll('button').find(button => button.text() === 'MSFT.US')!.trigger('click');
    expect(wrapper.findComponent({ name: 'StockDetailDialog' }).props('stock')).toMatchObject({
      code: 'MSFT.US', name: null,
    });
    wrapper.unmount();
  });
});
