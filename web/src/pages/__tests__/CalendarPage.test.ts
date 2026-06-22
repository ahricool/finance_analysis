import { calendarApi } from '@/api/calendar';
import type { CalendarEntryItem, FinanceEventItem } from '@/api/calendar';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CalendarPage from '../CalendarPage.vue';

vi.mock('@/api/calendar', () => ({
  calendarApi: {
    listEventsByDate: vi.fn(),
    listByDate: vi.fn(),
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

describe('CalendarPage detail modal', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = '';
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
  });

  it('opens, closes, and reopens finance event detail modal', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    expect(findDialog()).toBeNull();

    const eventButton = wrapper.get('article button');
    await eventButton.trigger('click');
    await flushPromises();

    const dialog = findDialog();
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('财经事件详情');
    expect(dialog?.textContent).toContain('Apple 财报发布');
    expect(dialog?.textContent).toContain('事件详情');

    const closeButton = document.body.querySelector('button[aria-label="关闭弹窗"]');
    expect(closeButton).not.toBeNull();
    await closeButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushPromises();

    expect(findDialog()).toBeNull();

    await eventButton.trigger('click');
    await flushPromises();
    expect(findDialog()?.textContent).toContain('财经事件详情');
  });

  it('opens, closes, and reopens calendar entry detail modal', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    const entryButtons = wrapper.findAll('article button');
    expect(entryButtons.length).toBeGreaterThanOrEqual(2);

    await entryButtons[1].trigger('click');
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

    await entryButtons[1].trigger('click');
    await flushPromises();
    expect(findDialog()?.textContent).toContain('日历记录详情');
  });

  it('clears detail when reloading entries after date change', async () => {
    const wrapper = mount(CalendarPage);
    await flushPromises();

    await wrapper.get('article button').trigger('click');
    await flushPromises();
    expect(findDialog()).not.toBeNull();

    const weekButtons = wrapper.findAll('.grid button');
    await weekButtons[1].trigger('click');
    await flushPromises();

    expect(findDialog()).toBeNull();
  });
});
