import { nextTick } from 'vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';
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
  vi.mocked(timelineApi.list).mockResolvedValue({ items: [item], total: 1, nextCursor: null, hasMore: false, limit: 20 });
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
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', category: 'news', importance: 'critical', actionability: 'watch', cursor: undefined }));
    wrapper.unmount();
  });
  it('appends older pages in API order without prioritizing importance', async () => {
    const older = { ...item, id: 'news:2', sourceId: 2, title: '较早的重要新闻', eventTime: '2026-09-06T07:00:00Z' };
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [{ ...item, importance: 'normal' }], total: 2, nextCursor: 'older-position', hasMore: true, limit: 20 })
      .mockResolvedValueOnce({ items: [older], total: 2, nextCursor: null, hasMore: false, limit: 20 });
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: undefined }));
    await wrapper.findAll('button').find(button => button.text() === '加载更多')!.trigger('click');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'older-position' }));
    expect(wrapper.findAll('[data-testid="timeline-item"]').map(row => row.text()))
      .toEqual([expect.stringContaining(item.title), expect.stringContaining(older.title)]);
    wrapper.unmount();
  });

  it('resets items and cursor on filter change and ignores stale load-more responses', async () => {
    let finishOlder!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    let finishFiltered!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [item], total: 3, nextCursor: 'old-position', hasMore: true, limit: 20 })
      .mockImplementationOnce(() => new Promise(resolve => { finishOlder = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { finishFiltered = resolve; }));
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const more = wrapper.findAll('button').find(button => button.text() === '加载更多')!;
    await more.trigger('click');
    await more.trigger('click');
    expect(timelineApi.list).toHaveBeenCalledTimes(2);
    await wrapper.findAll('button').find(button => button.text() === '美股')!.trigger('click');
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', cursor: undefined }));
    expect(wrapper.findAll('[data-testid="timeline-item"]')).toHaveLength(0);
    finishFiltered({ items: [{ ...item, title: '筛选结果' }], total: 1, nextCursor: null, hasMore: false, limit: 20 });
    await flushPromises();
    finishOlder({ items: [{ ...item, title: '过期响应' }], total: 3, nextCursor: 'stale', hasMore: true, limit: 20 });
    await flushPromises();
    expect(wrapper.get('[data-testid="timeline-item"]').text()).toContain('筛选结果');
    expect(wrapper.text()).not.toContain('过期响应');
    expect(wrapper.text()).not.toContain('加载更多');
    wrapper.unmount();
  });

  it.each(['market', 'category', 'importance', 'actionability', 'date', 'timezone'])('clears cursor on %s change', async (filter) => {
    let finish!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [item], total: 2, nextCursor: 'old-position', hasMore: true, limit: 20 })
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const pinia = createPinia();
    const wrapper = mount(TimelinePage, { global: { plugins: [pinia] } });
    await flushPromises();
    if (filter === 'market' || filter === 'category') {
      await wrapper.findAll('button').find(button => button.text() === (filter === 'market' ? '美股' : '新闻'))!.trigger('click');
    } else if (filter === 'importance' || filter === 'actionability') {
      await wrapper.get(`select[aria-label="${filter === 'importance' ? '重要度' : '行动等级'}"]`).setValue(filter === 'importance' ? 'high' : 'watch');
    } else if (filter === 'date') {
      wrapper.findComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-05');
    } else {
      const store = useTimezoneStore(pinia);
      store.setDisplayTimezone(store.displayTimezone === 'Asia/Shanghai' ? 'America/New_York' : 'Asia/Shanghai');
    }
    await nextTick();
    expect(wrapper.findAll('[data-testid="timeline-item"]')).toHaveLength(0);
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: undefined }));
    finish({ items: [], total: 0, nextCursor: null, hasMore: false, limit: 20 });
    await flushPromises();
    wrapper.unmount();
  });

});
