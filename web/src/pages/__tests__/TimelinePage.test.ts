import { nextTick } from 'vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TimelinePage from '../TimelinePage.vue';
import { timelineApi, type TimelineItem } from '@/api/timeline';

vi.mock('@/api/timeline', () => ({ timelineApi: { list: vi.fn() } }));

const news: TimelineItem = {
  id: 'news:1', sourceType: 'news', sourceId: 1, category: 'news', calendarType: null, market: 'US',
  eventTime: '2026-09-10T08:00:00Z', title: '芯片需求增长', summary: '订单展望上调', symbol: null,
  relatedSymbols: ['NVDA', 'AMD'], importance: 'critical', actionability: 'watch', impact: 'bullish',
  impactScore: 3, importanceScore: 9, eventType: 'guidance', detailType: 'news',
  detailPayload: { importanceReason: '盈利变化', content: 'FULL REPORT SHOULD NOT APPEAR IN FEED' },
};
const earnings: TimelineItem = {
  id: 'finance_event:2', sourceType: 'finance_event', sourceId: 2, category: 'event', calendarType: 'earnings',
  market: 'US', eventTime: '2026-10-01T20:00:00Z', title: 'NVDA Earnings', summary: '', symbol: 'NVDA',
  relatedSymbols: ['NVDA'], importance: 'high', actionability: 'watch', impact: null, impactScore: null,
  importanceScore: 9, eventType: 'earnings', detailType: 'event',
  detailPayload: { counterName: 'NVIDIA', reportingPeriod: 'Q3', marketSession: 'amc', currency: 'USD', epsEstimate: 1.32, allDay: true },
};
const macro: TimelineItem = {
  id: 'finance_event:3', sourceType: 'finance_event', sourceId: 3, category: 'event', calendarType: 'macro',
  market: 'US', eventTime: '2026-09-20T12:30:00Z', title: '美国 CPI', summary: '', symbol: null,
  relatedSymbols: [], importance: 'critical', actionability: 'watch', impact: null, impactScore: null,
  importanceScore: 10, eventType: 'macro', detailType: 'event', detailPayload: { allDay: false },
};
const analysis: TimelineItem = {
  id: 'report:4', sourceType: 'report', sourceId: 4, category: 'analysis', calendarType: null, market: 'US',
  eventTime: '2026-09-09T12:00:00Z', title: '美股盘前分析', summary: '等待趋势确认', symbol: null,
  relatedSymbols: [], importance: 'high', actionability: 'consider', impact: null, impactScore: null,
  importanceScore: null, eventType: 'us_premarket', detailType: 'report', detailPayload: { content: '# report' },
};

function respond(items: TimelineItem[]) {
  return { items, total: items.length, nextCursor: null, hasMore: false, limit: 20 };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-09-09T08:00:00Z'));
  vi.mocked(timelineApi.list).mockResolvedValue(respond([news]));
});

afterEach(() => vi.useRealTimers());

function clickTab(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll('button').find(button => button.text() === label)!.trigger('click');
}

describe('Public investment timeline', () => {
  it('offers only the five public tabs', async () => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const labels = wrapper.get('[aria-label="内容类型筛选"]').findAll('button').map(button => button.text());
    expect(labels).toEqual(['全部', '财报', '宏观', '新闻', '市场分析']);
    expect(wrapper.text()).not.toContain('财经事件');
    expect(wrapper.text()).not.toContain('笔记');
    wrapper.unmount();
  });

  it.each([
    ['财报', { category: 'event', calendar_type: 'earnings' }],
    ['宏观', { category: 'event', calendar_type: 'macro' }],
    ['新闻', { category: 'news' }],
    ['市场分析', { category: 'analysis' }],
  ])('maps the %s tab to a backend filter', async (label, expected) => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    await clickTab(wrapper, label);
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining(expected));
    wrapper.unmount();
  });

  it('sends no category filter for the 全部 tab and combines the market filter', async () => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith({ market: undefined, importance: undefined, end_date: '2026-09-09', cursor: undefined, limit: 20 });
    await clickTab(wrapper, '美股');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith({ market: 'US', importance: undefined, end_date: '2026-09-09', cursor: undefined, limit: 20 });
    wrapper.unmount();
  });

  it('turns the date picker into an end_date cutoff', async () => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    wrapper.findComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-30');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ end_date: '2026-09-30' }));
    expect(timelineApi.list).not.toHaveBeenLastCalledWith(expect.objectContaining({ start_date: expect.anything() }));
    wrapper.unmount();
  });

  it('renders every type as its own rounded card in API order', async () => {
    vi.mocked(timelineApi.list).mockResolvedValue(respond([earnings, macro, news, analysis]));
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const cards = wrapper.findAll('[data-testid="timeline-item"]');
    expect(cards).toHaveLength(4);
    for (const card of cards) expect(card.classes()).toContain('rounded-xl');
    expect(cards.map(card => card.text())).toEqual([
      expect.stringContaining('NVIDIA'),
      expect.stringContaining('美国 CPI'),
      expect.stringContaining('芯片需求增长'),
      expect.stringContaining('美股盘前分析'),
    ]);
    expect(cards[0]!.text()).toContain('财报');
    expect(cards[0]!.text()).toContain('盘后 AMC');
    expect(cards[0]!.text()).toContain('EPS 预期 $1.32');
    expect(cards[1]!.text()).toContain('宏观');
    expect(cards[2]!.text()).toContain('9/10');
    expect(cards[2]!.text()).toContain('NVDA');
    expect(wrapper.text()).not.toContain('FULL REPORT');
    wrapper.unmount();
  });

  it('appends older pages in API order without re-sorting', async () => {
    const older = { ...news, id: 'news:2', sourceId: 2, title: '较早的重要新闻', eventTime: '2026-09-06T07:00:00Z' };
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [{ ...news, importance: 'normal' }], total: 2, nextCursor: 'older-position', hasMore: true, limit: 20 })
      .mockResolvedValueOnce({ items: [older], total: 2, nextCursor: null, hasMore: false, limit: 20 });
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: undefined }));
    await clickTab(wrapper, '加载更多');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'older-position' }));
    expect(wrapper.findAll('[data-testid="timeline-item"]').map(row => row.text()))
      .toEqual([expect.stringContaining(news.title), expect.stringContaining(older.title)]);
    wrapper.unmount();
  });

  it('resets items and cursor on filter change and ignores stale load-more responses', async () => {
    let finishOlder!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    let finishFiltered!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [news], total: 3, nextCursor: 'old-position', hasMore: true, limit: 20 })
      .mockImplementationOnce(() => new Promise(resolve => { finishOlder = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { finishFiltered = resolve; }));
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const more = wrapper.findAll('button').find(button => button.text() === '加载更多')!;
    await more.trigger('click');
    await more.trigger('click');
    expect(timelineApi.list).toHaveBeenCalledTimes(2);
    await clickTab(wrapper, '美股');
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', cursor: undefined }));
    expect(wrapper.findAll('[data-testid="timeline-item"]')).toHaveLength(0);
    finishFiltered({ items: [{ ...news, title: '筛选结果' }], total: 1, nextCursor: null, hasMore: false, limit: 20 });
    await flushPromises();
    finishOlder({ items: [{ ...news, title: '过期响应' }], total: 3, nextCursor: 'stale', hasMore: true, limit: 20 });
    await flushPromises();
    expect(wrapper.get('[data-testid="timeline-item"]').text()).toContain('筛选结果');
    expect(wrapper.text()).not.toContain('过期响应');
    expect(wrapper.text()).not.toContain('加载更多');
    wrapper.unmount();
  });

  it.each(['market', 'tab', 'date', 'timezone', 'importance', 'preset'])('clears cursor on %s change', async (filter) => {
    let finish!: (value: Awaited<ReturnType<typeof timelineApi.list>>) => void;
    vi.mocked(timelineApi.list)
      .mockResolvedValueOnce({ items: [news], total: 2, nextCursor: 'old-position', hasMore: true, limit: 20 })
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const pinia = createPinia();
    const wrapper = mount(TimelinePage, { global: { plugins: [pinia] } });
    await flushPromises();
    if (filter === 'market' || filter === 'tab') {
      await clickTab(wrapper, filter === 'market' ? '美股' : '宏观');
    } else if (filter === 'importance') {
      await wrapper.get('select[aria-label="重要性"]').setValue('high');
    } else if (filter === 'preset') {
      await clickTab(wrapper, '未来7天');
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

  it('opens an earnings detail dialog with provider attribution', async () => {
    vi.mocked(timelineApi.list).mockResolvedValue(respond([{
      ...earnings,
      detailPayload: { ...earnings.detailPayload, sourceProviders: ['longbridge', 'yfinance'], reportedEps: 1.46, epsSurprisePct: 10.6 },
    }]));
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] }, attachTo: document.body });
    await flushPromises();
    await wrapper.get('[data-testid="timeline-item"]').trigger('click');
    await flushPromises();
    const dialog = document.body.textContent ?? '';
    expect(dialog).toContain('实际 EPS');
    expect(dialog).toContain('$1.46');
    expect(dialog).toContain('longbridge · yfinance');
    wrapper.unmount();
  });
});

describe('cutoff presets and columns', () => {
  it.each([['今天', '2026-09-09', '2026年9月9日'], ['未来7天', '2026-09-16', '2026年9月16日'], ['未来14天', '2026-09-23', '2026年9月23日'], ['未来30天', '2026-10-09', '2026年10月9日']])('selects %s and displays the actual date', async (label, endDate, display) => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(wrapper.get('[aria-label="今天"]').attributes('aria-pressed')).toBe('true');
    expect(wrapper.findComponent(AppDatePicker).text()).toContain('2026年9月9日');
    expect(wrapper.findComponent(AppDatePicker).props('clearable')).toBe(false);
    await clickTab(wrapper, label);
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ end_date: endDate }));
    expect(wrapper.get(`[aria-label="${label}"]`).attributes('aria-pressed')).toBe('true');
    expect(wrapper.findComponent(AppDatePicker).text()).toContain(display);
    wrapper.unmount();
  });

  it.each(['今天', '未来7天', '未来14天', '未来30天'])('recomputes %s at a timezone date boundary and preserves custom dates', async label => {
    vi.setSystemTime(new Date('2026-09-09T01:00:00Z'));
    const pinia = createPinia();
    const wrapper = mount(TimelinePage, { global: { plugins: [pinia] } });
    await clickTab(wrapper, label);
    const shanghai = wrapper.findComponent(AppDatePicker).props('modelValue')!;
    useTimezoneStore(pinia).setDisplayTimezone('America/New_York');
    await flushPromises();
    const expected = { '今天': '2026-09-08', '未来7天': '2026-09-15', '未来14天': '2026-09-22', '未来30天': '2026-10-08' }[label];
    expect(wrapper.findComponent(AppDatePicker).props('modelValue')).toBe(expected);
    useTimezoneStore(pinia).setDisplayTimezone('Asia/Shanghai');
    await flushPromises();
    expect(wrapper.findComponent(AppDatePicker).props('modelValue')).toBe(shanghai);
    wrapper.findComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-10-20');
    await flushPromises();
    expect(wrapper.findComponent(AppDatePicker).text()).toContain('2026年10月20日');
    expect(wrapper.get('[aria-label="截止日期快捷筛选"]').findAll('[aria-pressed="true"]')).toHaveLength(0);
    useTimezoneStore(pinia).setDisplayTimezone('America/New_York');
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ end_date: '2026-10-20' }));
    wrapper.findComponent(AppDatePicker).vm.$emit('update:modelValue', '');
    await flushPromises();
    expect(wrapper.findComponent(AppDatePicker).props('modelValue')).toBe('2026-10-20');
    wrapper.unmount();
  });

  it.each(['critical', 'high', 'normal', 'low', ''])('combines importance %s with market, earnings and cutoff', async importance => {
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await clickTab(wrapper, '美股');
    await clickTab(wrapper, '财报');
    await clickTab(wrapper, '未来30天');
    await wrapper.get('select[aria-label="重要性"]').setValue(importance);
    await flushPromises();
    expect(timelineApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', category: 'event', calendar_type: 'earnings', end_date: '2026-10-09', importance: importance || undefined, cursor: undefined }));
    wrapper.unmount();
  });

  it('keeps one uninterrupted DOM sequence within each day columns container', async () => {
    const sameDay = [earnings, macro, news, analysis].map((item, index) => ({ ...item, eventTime: `2026-09-09T0${7-index}:00:00Z` }));
    vi.mocked(timelineApi.list).mockResolvedValue(respond(sameDay));
    const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const columns = wrapper.findAll('[data-testid="timeline-columns"]');
    expect(columns).toHaveLength(1);
    expect(columns[0]!.classes()).toEqual(expect.arrayContaining(['columns-1', 'lg:columns-2']));
    expect(columns[0]!.findAll('.break-inside-avoid')).toHaveLength(4);
    expect(columns[0]!.findAll('[data-testid="timeline-item"]').map(card => card.attributes('aria-label'))).toEqual(sameDay.map(item => `查看${item.title}`));
    wrapper.unmount();
  });
});


it.each([
  ['USD', 1.32, '$1.32'], ['CNY', 15.2, '¥15.20'], ['HKD', 3.5, 'HK$3.50'],
  [null, 2.1, '2.10'], ['unknown', 2.1, '2.10'],
] as const)('renders %s EPS in both the earnings card and detail dialog', async (currency, value, expected) => {
  vi.mocked(timelineApi.list).mockResolvedValue(respond([{
    ...earnings, detailPayload: { ...earnings.detailPayload, currency, epsEstimate: value, reportedEps: value },
  }]));
  const wrapper = mount(TimelinePage, { global: { plugins: [createPinia()] }, attachTo: document.body });
  await flushPromises();
  const card = wrapper.get('[data-testid="timeline-item"]');
  expect(card.text()).toContain(`EPS 预期 ${expected}`);
  expect(card.text()).toContain(`实际 ${expected}`);
  await card.trigger('click');
  await flushPromises();
  const facts = Array.from(document.body.querySelectorAll('[role="dialog"] dl > div'));
  for (const label of ['EPS 预期', '实际 EPS']) {
    expect(facts.find(fact => fact.querySelector('dt')?.textContent?.trim() === label)?.querySelector('dd')?.textContent?.trim()).toBe(expected);
  }
  wrapper.unmount();
});
