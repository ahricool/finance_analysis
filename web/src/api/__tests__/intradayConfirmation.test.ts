import { describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { intradayConfirmationApi as api } from '../intradayConfirmation';
vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
describe('intraday snapshot API', () => {
  it('preserves null metrics and quote timestamps while converting window keys', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { summary: { WAIT: 1, CONFIRMED: 0, FAILED: 0, total: 1 },
      items: [{ metrics: { return_5m: .01, return_15m: null, quote_time: '2026-09-21T13:35:00Z' } }] } });
    const result = await api.read('US', 'WAIT', 'trend');
    expect(result.summary.wait).toBe(1);
    expect(result.items[0]?.metrics).toEqual({ return5M: .01, return15M: null, quoteTime: '2026-09-21T13:35:00Z' });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/intraday-confirmation', { params: { market: 'US', state: 'WAIT', candidate_source: 'trend' } });
  });
  it('only enqueues computation on explicit POST', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { task_id: 'job' } });
    expect(await api.run('CN')).toEqual({ taskId: 'job' });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/intraday-confirmation/run', { market: 'CN' });
  });
});
