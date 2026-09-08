import { expect, it, vi } from 'vitest';
import apiClient from '../index';
import { timelineApi } from '../timeline';

vi.mock('../index', () => ({ default: { get: vi.fn() } }));
vi.mock('@/utils/format', () => ({ getDisplayTimezone: () => 'Asia/Shanghai' }));

it('passes opaque cursor and maps cursor metadata to camelCase', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: {
    items: [], total: 42, limit: 20, next_cursor: 'opaque-next', has_more: true,
  } });
  const result = await timelineApi.list({ cursor: 'opaque-input', market: 'US', limit: 20 });
  expect(apiClient.get).toHaveBeenCalledWith('/api/v1/timeline', {
    params: { cursor: 'opaque-input', market: 'US', limit: 20, timezone: 'Asia/Shanghai' },
  });
  expect(result).toEqual({ items: [], total: 42, limit: 20, nextCursor: 'opaque-next', hasMore: true });
});

it('sends the cutoff date and calendar type as plain query parameters', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 0, limit: 20, next_cursor: null, has_more: false } });
  await timelineApi.list({ end_date: '2026-09-30', category: 'event', calendar_type: 'earnings' });
  expect(apiClient.get).toHaveBeenCalledWith('/api/v1/timeline', {
    params: { end_date: '2026-09-30', category: 'event', calendar_type: 'earnings', timezone: 'Asia/Shanghai' },
  });
});

it('no longer exposes note mutations or a summary endpoint', () => {
  expect(Object.keys(timelineApi)).toEqual(['list']);
});
