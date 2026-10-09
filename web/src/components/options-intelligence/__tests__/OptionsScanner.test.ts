import { describe, it, expect, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import OptionsIntelligencePage from '@/pages/market/OptionsIntelligencePage.vue';
import { optionsIntelligenceApi } from '@/api/optionsIntelligence';
vi.mock('@/api/optionsIntelligence', () => ({ optionsIntelligenceApi: { scan: vi.fn() } }));
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ currentUser: { role: 'user' } }) }));
const mock = vi.mocked(optionsIntelligenceApi.scan);
const stubs = { StockDetailDialog: true, OptionsDataControls: true, FieldSelect: true, OptionHelp: true, PageHeader: true };
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
