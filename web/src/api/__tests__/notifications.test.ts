import { expect, it, vi } from 'vitest';
import apiClient from '../index';
import { notificationsApi } from '../notifications';
vi.mock('../index', () => ({ default: { get: vi.fn() } }));

it('uses message endpoints and maps previews without delivery fields', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: {
    items: [{ id: 1, uid: null, title: '报告', content_preview: '摘要', route_type: 'report', severity: 'info', created_at: '2026-09-11T00:00:00Z' }],
    total: 1, page: 2, page_size: 20,
  } });
  const result = await notificationsApi.list({ page: 2, keyword: '报告', route_type: 'report' });
  expect(apiClient.get).toHaveBeenCalledWith('/api/v1/notifications', { params: { page: 2, keyword: '报告', route_type: 'report' } });
  expect(result.items[0]?.contentPreview).toBe('摘要');
  expect(result.pageSize).toBe(20);
  vi.mocked(apiClient.get).mockResolvedValue({ data: { id: 1, title: '报告', content: '# 完整报告', route_type: 'report' } });
  expect((await notificationsApi.detail(1)).content).toBe('# 完整报告');
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/notifications/1');
});
