import { calendarApi } from '@/api/calendar';
import type { CalendarEntryItem, FinanceEventItem } from '@/api/calendar';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CalendarPage from '../CalendarPage.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';

vi.mock('@/api/calendar', () => ({
  calendarApi: {
    listEventsByDate: vi.fn(),
    listByDate: vi.fn(),
    getSummary: vi.fn(),
  },
}));

const mockEvent: FinanceEventItem = {
  id: 1,
  provider: 'longbridge',
  provider_event_id: 'evt-1',
  event_key: 'key-1',
  calendar_type: 'earnings',
  market: 'US',
  symbol: 'AAPL',
  counter_name: 'Apple Inc.',
  event_type: null,
  activity_type: null,
  event_date: '2026-06-22',
  event_datetime: '2026-06-22T14:00:00Z',
  date_type: null,
  financial_market_time: null,
  title: 'Apple 财报发布',
  content: '## 事件详情\n\n预计盘后公布。',
  star: 3,
  currency: 'USD',
  data_kv_json: null,
  importance_score: 9,
  importance_reason: '大型科技公司财报，市场关注度较高。',
  importance_confidence: 0.88,
  importance_model: 'test-model',
  importance_prompt_version: 'v1',
  importance_input_hash: 'hash-1',
  importance_scored_at: '2026-06-20T01:00:00Z',
  first_seen_at: '2026-06-20T00:00:00Z',
  last_seen_at: '2026-06-20T00:00:00Z',
  notified_at: null,
  created_at: '2026-06-20T00:00:00Z',
  updated_at: '2026-06-20T00:00:00Z',
};

const mockEntry: CalendarEntryItem = {
  id: 2,
  time: '2026-06-22T08:00:00Z',
  title: '美股盘前扫描',
  content: '## 执行结果\n\n已完成。',
  type: 'scheduled_us_premarket',
  created_at: '2026-06-22T08:00:00Z',
  updated_at: '2026-06-22T08:00:00Z',
};

function findDialog() {
  return document.body.querySelector('[role="dialog"]');
}

function findEventButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('button').find((button) => button.text().includes('Apple 财报发布'));
}

function findEntryButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('button').find((button) => button.text().includes('美股盘前扫描'));
}

function summaryFor(startDate = '2026-06-25', endDate = '2026-07-01') {
  return {
    start_date: startDate,
    end_date: endDate,
    items: [
      { date: startDate, finance_event_count: 3, calendar_entry_count: 1 },
      { date: '2026-06-26', finance_event_count: 6, calendar_entry_count: 0 },
      { date: '2026-06-27', finance_event_count: 2, calendar_entry_count: 5 },
      { date: '2026-06-28', finance_event_count: 0, calendar_entry_count: 6 },
      { date: '2026-06-29', finance_event_count: 1, calendar_entry_count: 2 },
      { date: '2026-06-30', finance_event_count: 0, calendar_entry_count: 0 },
      { date: endDate, finance_event_count: 4, calendar_entry_count: 3 },
    ],
  };
}

function dayButtons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('[data-testid="calendar-day"]');
}

describe('CalendarPage', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-25T20:00:00Z'));
    localStorage.clear();
    setActivePinia(createPinia());
    document.body.innerHTML = '';
    vi.clearAllMocks();
    vi.mocked(calendarApi.listEventsByDate).mockResolvedValue({
      date: '2026-06-22',
      items: [mockEvent],
      total: 1,
    });
    vi.mocked(calendarApi.listByDate).mockResolvedValue({
      date: '2026-06-22',
      items: [mockEntry],
      total: 1,
    });
    vi.mocked(calendarApi.getSummary).mockResolvedValue(summaryFor());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the default 7-day range with today in the second selected cell', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    const buttons = dayButtons(wrapper);
    expect(buttons).toHaveLength(7);
    expect(buttons[0].text()).toContain('06/25');
    expect(buttons[1].text()).toContain('06/26');
    expect(buttons[1].classes()).toContain('text-primary');
    expect(calendarApi.listEventsByDate).toHaveBeenCalledWith('2026-06-26');
    expect(calendarApi.listByDate).toHaveBeenCalledWith('2026-06-26');
    expect(calendarApi.getSummary).toHaveBeenCalledWith('2026-06-25', '2026-07-01');
  });

  it('returns to the default range and selected today from the today button', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    await wrapper.get('button[aria-label="下一周期"]').trigger('click');
    await flushPromises();
    expect(dayButtons(wrapper)[1].text()).toContain('07/03');

    await wrapper.findAll('button').find((button) => button.text() === '今天')!.trigger('click');
    await flushPromises();

    const buttons = dayButtons(wrapper);
    expect(buttons[0].text()).toContain('06/25');
    expect(buttons[1].text()).toContain('06/26');
    expect(buttons[1].classes()).toContain('text-primary');
    expect(calendarApi.listEventsByDate).toHaveBeenLastCalledWith('2026-06-26');
    expect(calendarApi.getSummary).toHaveBeenLastCalledWith('2026-06-25', '2026-07-01');
  });

  it('moves the visible range by 7 days with previous and next buttons', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    await wrapper.get('button[aria-label="下一周期"]').trigger('click');
    await flushPromises();
    expect(dayButtons(wrapper)[0].text()).toContain('07/02');
    expect(calendarApi.getSummary).toHaveBeenLastCalledWith('2026-07-02', '2026-07-08');

    await wrapper.get('button[aria-label="上一周期"]').trigger('click');
    await flushPromises();
    expect(dayButtons(wrapper)[0].text()).toContain('06/25');
    expect(calendarApi.getSummary).toHaveBeenLastCalledWith('2026-06-25', '2026-07-01');
  });

  it('shows both summary counts with count tone classes', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    const buttons = dayButtons(wrapper);
    expect(buttons[0].text()).toContain('财经 3');
    expect(buttons[0].text()).toContain('记录 1');
    expect(buttons[0].find('[data-count-tone="warning"]').text()).toBe('3');
    expect(buttons[0].find('[data-count-tone="primary"]').text()).toBe('1');
    expect(buttons[1].find('[data-count-tone="danger"]').text()).toBe('6');
    expect(buttons[1].find('[data-count-tone="muted"]').text()).toBe('0');
  });

  it('only reloads single-day details when switching dates', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    await dayButtons(wrapper)[2].trigger('click');
    await flushPromises();

    expect(calendarApi.listEventsByDate).toHaveBeenCalledTimes(2);
    expect(calendarApi.listEventsByDate).toHaveBeenLastCalledWith('2026-06-27');
    expect(calendarApi.listByDate).toHaveBeenCalledTimes(2);
    expect(calendarApi.getSummary).toHaveBeenCalledTimes(1);
  });

  it('reloads range summary when changing date ranges', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    await wrapper.get('button[aria-label="下一周期"]').trigger('click');
    await flushPromises();

    expect(calendarApi.getSummary).toHaveBeenCalledTimes(2);
    expect(calendarApi.getSummary).toHaveBeenLastCalledWith('2026-07-02', '2026-07-08');
    expect(calendarApi.listEventsByDate).toHaveBeenLastCalledWith('2026-07-03');
  });

  it('recomputes today and the range when timezone changes', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    useTimezoneStore().setDisplayTimezone('America/New_York');
    await flushPromises();

    const buttons = dayButtons(wrapper);
    expect(buttons[0].text()).toContain('06/24');
    expect(buttons[1].text()).toContain('06/25');
    expect(calendarApi.listEventsByDate).toHaveBeenLastCalledWith('2026-06-25');
    expect(calendarApi.getSummary).toHaveBeenLastCalledWith('2026-06-24', '2026-06-30');
  });

  it('opens, closes, and reopens finance event detail modal', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    expect(findDialog()).toBeNull();

    const eventButton = findEventButton(wrapper);
    expect(eventButton).toBeDefined();
    await eventButton!.trigger('click');
    await flushPromises();

    const dialog = findDialog();
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('财经事件详情');
    expect(dialog?.textContent).toContain('Apple 财报发布');
    expect(dialog?.textContent).toContain('事件详情');
    expect(dialog?.textContent).toContain('9/10');
    expect(dialog?.textContent).toContain('大型科技公司财报');

    const closeButton = document.body.querySelector('button[aria-label="关闭弹窗"]');
    expect(closeButton).not.toBeNull();
    await closeButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushPromises();

    expect(findDialog()).toBeNull();

    await eventButton!.trigger('click');
    await flushPromises();
    expect(findDialog()?.textContent).toContain('财经事件详情');
  });

  it('opens, closes, and reopens calendar entry detail modal', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    const entryButton = findEntryButton(wrapper);
    expect(entryButton).toBeDefined();

    await entryButton!.trigger('click');
    await flushPromises();

    const dialog = findDialog();
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('日历记录详情');
    expect(dialog?.textContent).toContain('美股盘前扫描');
    expect(dialog?.textContent).toContain('执行结果');

    const backdrop = document.body.querySelector('[role="presentation"] > div');
    expect(backdrop).not.toBeNull();
    await backdrop!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushPromises();

    expect(findDialog()).toBeNull();

    await entryButton!.trigger('click');
    await flushPromises();
    expect(findDialog()?.textContent).toContain('日历记录详情');
  });

  it('clears detail when reloading entries after date change', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    const eventButton = findEventButton(wrapper);
    expect(eventButton).toBeDefined();
    await eventButton!.trigger('click');
    await flushPromises();
    expect(findDialog()).not.toBeNull();

    await dayButtons(wrapper)[2].trigger('click');
    await flushPromises();

    expect(findDialog()).toBeNull();
  });
});
