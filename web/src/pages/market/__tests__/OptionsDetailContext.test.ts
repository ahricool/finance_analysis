import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import OptionsIntelligencePage from '../OptionsIntelligencePage.vue';
import { optionsIntelligenceApi, type OptionMetrics } from '@/api/optionsIntelligence';
vi.mock('@/api/optionsIntelligence', () => ({ optionsIntelligenceApi: { scan: vi.fn(), run: vi.fn() } }));
const item = { symbol: 'AAPL.US', name: 'Apple', status: 'warming_up', scores: null, eventTypes: [], contracts: [], observedAt: '2026-10-12T14:00:00Z' } as unknown as OptionMetrics;
beforeEach(() => vi.resetAllMocks());
describe('options source context in the unified modal', () => {
  it.each(['official', 'preview'] as const)('passes the actual %s scan date to every detail tab', async mode => {
    vi.mocked(optionsIntelligenceApi.scan).mockResolvedValue({ items: [item], tradeDate: '2026-10-12', availableDates: ['2026-10-12'] });
    const wrapper = mount(OptionsIntelligencePage, { global: { plugins: [createPinia()], stubs: { RouterLink: true, OptionsDataControls: true, StockDetailDialog: true } } });
    await flushPromises();
    if (mode === 'preview') {
      wrapper.findComponent({ name: 'OptionsDataControls' }).vm.$emit('update:mode', mode);
      await flushPromises();
    }
    await wrapper.findAll('button').find(button => button.text().includes('AAPL.US'))!.trigger('click');
    expect(wrapper.findComponent({ name: 'StockDetailDialog' }).props()).toMatchObject({ stock: { code: 'AAPL.US', name: 'Apple' }, initialTab: 'overview', optionsView: mode, optionsDate: '2026-10-12' });
    expect(optionsIntelligenceApi.scan).toHaveBeenLastCalledWith({ view: mode, tradeDate: undefined });
    await wrapper.get('tbody tr').trigger('click');
    expect(wrapper.findComponent({ name: 'StockDetailDialog' }).props('initialTab')).toBe('options');
    wrapper.unmount();
  });
});
