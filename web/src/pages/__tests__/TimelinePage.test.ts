import { mount, flushPromises } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TimelinePage from '../TimelinePage.vue';
import { timelineApi, type TimelineItem } from '@/api/timeline';

vi.mock('@/api/timeline', () => ({ timelineApi: { list: vi.fn(), summary: vi.fn(), saveNote: vi.fn(), deleteNote: vi.fn() } }));
const item: TimelineItem = { id: 'news:1', sourceType: 'news', sourceId: 1, category: 'news', market: 'US',
  eventTime: '2026-09-06T08:00:00Z', title: '芯片需求增长', summary: '订单展望上调', symbol: null,
  relatedSymbols: ['NVDA', 'AMD'], importance: 'critical', actionability: 'watch', impact: 'bullish',
  impactScore: 3, importanceScore: 9, eventType: 'guidance', detailType: 'news',
  detailPayload: { importanceReason: '盈利变化', content: 'FULL REPORT SHOULD NOT APPEAR IN FEED' } };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(timelineApi.list).mockResolvedValue({ items: [item], total: 1, page: 1, limit: 20 });
  vi.mocked(timelineApi.summary).mockResolvedValue([]);
});

describe('Investment Timeline feed', () => {
  it('renders individual news with compact decision metadata', async () => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(wrapper.get('[data-testid="timeline-item"]').text()).toContain('芯片需求增长');
    expect(wrapper.text()).toContain('9/10');
    expect(wrapper.text()).toContain('NVDA');
    expect(wrapper.text()).not.toContain('FULL REPORT');
    expect(wrapper.text()).not.toContain('新闻日历');
    wrapper.unmount();
  });
  it('combines market, category, importance and action filters in one API', async () => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '美股')!.trigger('click');
    await wrapper.findAll('button').find(button => button.text() === '新闻')!.trigger('click');
    await wrapper.get('select[aria-label="重要度"]').setValue('critical');
    await wrapper.get('select[aria-label="行动等级"]').setValue('watch');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', category: 'news', importance: 'critical', actionability: 'watch', page: 1 }));
    wrapper.unmount();
  });
});
