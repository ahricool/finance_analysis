import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi, type StockClassification } from '@/api/stocks';
import StockIndustryTags from '../StockIndustryTags.vue';

vi.mock('@/api/stocks', () => ({ stocksApi: { classification: vi.fn() } }));
const result = (name: string): StockClassification => ({ code: '600519.SH', market: 'CN', memberships: {
  indices: [], industries: [{ code: '881101.TI', name, membersObservedAt: '2026-10-11T02:00:00Z' }],
} });

describe('StockIndustryTags', () => {
  beforeEach(() => vi.resetAllMocks());

  it('shows weekly membership independently of daily strength results', async () => {
    vi.mocked(stocksApi.classification).mockResolvedValue(result('食品饮料'));
    const wrapper = mount(StockIndustryTags, { props: { code: '600519.SH' } });
    expect(wrapper.text()).toContain('正在加载所属行业');
    await flushPromises();
    expect(wrapper.text()).toContain('食品饮料');
    expect(wrapper.text()).toContain('每周同步');
    expect(stocksApi.classification).toHaveBeenCalledWith('600519.SH', expect.any(AbortSignal));
    wrapper.unmount();
  });

  it('aborts stale requests when switching stocks and closing the dialog', async () => {
    let finish!: (data: StockClassification) => void;
    vi.mocked(stocksApi.classification).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(StockIndustryTags, { props: { code: '600519.SH' } });
    const signal = vi.mocked(stocksApi.classification).mock.calls[0]![1]!;
    vi.mocked(stocksApi.classification).mockResolvedValue(result('农业'));
    await wrapper.setProps({ code: '600001.SH' });
    await flushPromises();
    finish(result('旧行业')); await flushPromises();
    expect(signal.aborted).toBe(true);
    expect(wrapper.text()).toContain('农业');
    expect(wrapper.text()).not.toContain('旧行业');
    const active = vi.mocked(stocksApi.classification).mock.calls[1]![1]!;
    wrapper.unmount();
    expect(active.aborted).toBe(true);
  });

  it('shows empty state and allows independent retry after a failure', async () => {
    vi.mocked(stocksApi.classification).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({
      code: '600519.SH', market: 'CN', memberships: { indices: [], industries: [] },
    });
    const wrapper = mount(StockIndustryTags, { props: { code: '600519.SH' } });
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    const retry = wrapper.findAll('button').find(button => button.text() === '重试行业')!;
    await retry.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('暂无所属行业数据');
    expect(stocksApi.classification).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
