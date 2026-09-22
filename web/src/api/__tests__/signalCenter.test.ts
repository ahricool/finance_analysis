import { describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { signalCenterApi } from '../signalCenter';
vi.mock('../index', () => ({ default: { get: vi.fn() } }));
describe('Signal Center API', () => {
  it('passes exact historical date and converts nested evidence', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { requested_dates: { CN: '2026-09-22', US: '2026-09-22' }, items: [{ signal_date: '2026-09-22', candidate_snapshot: { source_availability: { trend: { data_as_of: '2026-09-22' } } } }] } });
    const result = await signalCenterApi.daily('2026-09-22');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/signal-center/daily', { params: { signal_date: '2026-09-22' } });
    expect(result.requestedDates.CN).toBe('2026-09-22');
    expect(result.requestedDates.US).toBe('2026-09-22');
    expect(result.items[0]!.candidateSnapshot.sourceAvailability.trend!.dataAsOf).toBe('2026-09-22');
  });
  it('reads historical detail without a generation request', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { market: 'US', signal_date: '2026-09-21' } });
    expect((await signalCenterApi.detail('US', '2026-09-21')).signalDate).toBe('2026-09-21');
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/signal-center/US/2026-09-21');
  });
});
