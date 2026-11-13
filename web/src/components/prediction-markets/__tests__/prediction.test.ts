import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import PredictionEventCard from '../PredictionEventCard.vue';
import PredictionEventsPage from '@/pages/market/PredictionEventsPage.vue';
import { predictionApi, type PredictionEvent, type EventPage } from '@/api/predictionMarkets';
vi.mock('@/api/predictionMarkets', () => ({ predictionApi: { live: vi.fn(), history: vi.fn(), tags: vi.fn(), events: vi.fn() } }));
vi.mock('../PredictionHistory.vue', () => ({ __esModule: true, default: { props: ['eventId', 'marketId', 'outcomeId'], template: '<div data-testid="history">{{ outcomeId }}</div>' } }));
const event: PredictionEvent = { eventId: '1', title: 'Nvidia IPO event', description: '', url: 'https://polymarket.com/event/example', tags: [], endAt: null, closed: false, retained: true, ruleRetained: true, ruleReason: 'selected_tag', manualRetained: null, syncedAt: '2026-11-13T00:00:00Z' };
const response: EventPage = { status: 'ready', items: [event], total: 1, page: 1, pageSize: 5 };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(predictionApi.live).mockResolvedValue({ status: 'ready', fetchedAt: '2026-11-13T00:00:00Z', markets: [{ id: 'm', question: 'Question', version: 'v2', closed: false, resolved: false, endAt: null, outcomes: Array.from({ length: 4 }, (_, i) => ({ id: String(i), label: `Outcome ${i}`, probability: i === 0 ? 0 : null, priceType: 'gamma_outcome_price', missingReason: null })) }] });
  vi.mocked(predictionApi.events).mockResolvedValue({ ...response, pageSize: 10 });
  vi.mocked(predictionApi.tags).mockResolvedValue({ status: 'ready', items: ['tech', 'business'].map((s, i) => ({ tagId: String(i), slug: s, label: s, visible: true, ruleGroup: s, manualVisible: null, eventCount: 1 })) });
});
describe('prediction event shared UI', () => {
  it('keeps topic visible, zero valid, all outcomes expandable, history lazy', async () => {
    const wrapper = mount(PredictionEventCard, { props: { event } }); await flushPromises();
    expect(wrapper.text()).toContain('Nvidia IPO event'); expect(wrapper.text()).not.toContain('匹配');
    expect(wrapper.text()).toContain('0.0%'); expect(wrapper.text()).toContain('暂无');
    expect(wrapper.text()).not.toContain('Outcome 3'); expect(predictionApi.history).not.toHaveBeenCalled();
    await wrapper.findAll('button').find(b => b.text().includes('展开全部'))!.trigger('click');
    expect(wrapper.text()).toContain('Outcome 3');
    await wrapper.findAll('button').find(b => b.text() === '变化与趋势')!.trigger('click'); await flushPromises();
    expect(wrapper.get('[data-testid="history"]').text()).toBe('0'); wrapper.unmount();
  });
  it('preserves topic on dynamic outage and aborts on unmount', async () => {
    vi.mocked(predictionApi.live).mockResolvedValue({ status: 'unavailable' });
    const wrapper = mount(PredictionEventCard, { props: { event } }); await flushPromises();
    expect(wrapper.text()).toContain(event.title); expect(wrapper.text()).toContain('动态选项暂不可用');
    const signal = vi.mocked(predictionApi.live).mock.calls[0]![1]!;
    wrapper.unmount(); expect(signal.aborted).toBe(true);
  });
  it('passes tags as OR selection and does not expose administrator UI', async () => {
    const wrapper = mount(PredictionEventsPage, { global: { plugins: [createPinia()], stubs: { PredictionEventCard: true } } }); await flushPromises();
    for (const label of ['tech', 'business']) { await wrapper.findAll('button').find(b => b.text().startsWith(label))!.trigger('click'); await flushPromises(); }
    expect(vi.mocked(predictionApi.events).mock.calls.at(-1)![0].tagIds).toEqual(['0', '1']);
    expect(wrapper.text()).not.toContain('共享配置管理'); expect(wrapper.text()).not.toContain('实时概率排序'); wrapper.unmount();
  });
});
