import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { beforeEach, expect, it, vi } from 'vitest';
import IndustryDetailPanel from '../IndustryDetailPanel.vue';
const api = vi.hoisted(() => ({ stockContext: vi.fn() }));
vi.mock('@/api/industryStrength', () => ({ industryStrengthApi: api }));
const industry = { industryCode: '881101.TI', industryName: '食品', tradeDate: '2026-09-21', state: 'STRONG', strengthRank: 2, rankTotal: 80, strengthScore: 80, membersObservedAt: '2026-09-21T10:00:00Z' };
const props = { symbol: '600519.SH', market: 'CN' as const };
const global = { plugins: [createPinia()], stubs: { RouterLink: { name: 'RouterLink', props: ['to'], template: '<a><slot /></a>' } } };
beforeEach(() => { vi.resetAllMocks(); api.stockContext.mockResolvedValue([industry]); });
it('keeps industry date, ranking, observation time and dated source link', async () => {
  const wrapper = mount(IndustryDetailPanel, { props, global }); await flushPromises();
  for (const text of ['食品', '2026-09-21', '#2', '强度 80', '当前成分观测时间', '不随其他研究页签']) expect(wrapper.text()).toContain(text);
  expect(wrapper.findComponent({ name: 'RouterLink' }).props('to')).toEqual({ path: '/research/industry-strength', query: { industry: '881101.TI', tradeDate: '2026-09-21' } });
  wrapper.unmount();
});
it('clears stale stock results and does not fetch outside CN', async () => {
  let finish!: (rows: unknown[]) => void;
  api.stockContext.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const wrapper = mount(IndustryDetailPanel, { props, global });
  await wrapper.setProps({ symbol: 'AAPL.US', market: 'US' });
  finish([industry]); await flushPromises();
  expect(wrapper.text()).not.toContain('食品'); expect(api.stockContext).toHaveBeenCalledTimes(1); wrapper.unmount();
});
it('offers retry for failures and a neutral empty state for missing coverage', async () => {
  api.stockContext.mockRejectedValueOnce(new Error('offline'));
  const wrapper = mount(IndustryDetailPanel, { props, global }); await flushPromises();
  api.stockContext.mockRejectedValueOnce({ response: { status: 404 } });
  await wrapper.findAll('button').find(button => button.text().includes('重试行业背景'))!.trigger('click'); await flushPromises();
  expect(wrapper.text()).toContain('暂无正式行业结果'); expect(wrapper.find('button').exists()).toBe(false); wrapper.unmount();
});
