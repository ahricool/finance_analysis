import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import NotificationsPage from '../NotificationsPage.vue';
import { notificationsApi } from '@/api/notifications';
vi.mock('@/api/notifications', () => ({ notificationsApi: { list: vi.fn(), detail: vi.fn() } }));
vi.mock('@/utils/format', () => ({ formatDateTimeInDisplayTimezone: (value: string) => value }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(notificationsApi.list).mockResolvedValue({ items: [{
    id: 1, uid: 42, title: '每日分析', contentPreview: '摘要', routeType: 'report', severity: 'info', createdAt: '2026-09-11T00:00:00Z',
  }], total: 1, page: 1, pageSize: 20 });
  vi.mocked(notificationsApi.detail).mockResolvedValue({
    id: 1, title: '每日分析', content: '# 完整正文', routeType: 'report', severity: 'info', createdAt: '2026-09-11T00:00:00Z',
  });
});

it('loads previews, applies search and reset, and fetches full detail only when opened', async () => {
  const wrapper = mount(NotificationsPage, { attachTo: document.body });
  await flushPromises();
  expect(wrapper.text()).toContain('每日分析');
  expect(wrapper.text()).not.toContain('uid');
  expect(notificationsApi.detail).not.toHaveBeenCalled();
  await wrapper.get('#notification-keyword').setValue('风险');
  await wrapper.get('form').trigger('submit');
  await flushPromises();
  expect(notificationsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '风险', page: 1 }));
  await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click');
  await flushPromises();
  expect(notificationsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: undefined, page: 1 }));
  await wrapper.findAll('button').find(button => button.text() === '每日分析')!.trigger('click');
  await flushPromises();
  expect(notificationsApi.detail).toHaveBeenCalledWith(1);
  expect(document.body.textContent).toContain('完整正文');
  wrapper.unmount();
});

it('renders an empty state', async () => {
  vi.mocked(notificationsApi.list).mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
  const wrapper = mount(NotificationsPage);
  await flushPromises();
  expect(wrapper.text()).toContain('暂无符合条件的消息');
  wrapper.unmount();
});
