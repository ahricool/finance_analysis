import { describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { intradayConfirmationApi as api } from '../intradayConfirmation';
vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
describe('intraday snapshot API', () => {
  it('preserves null metrics and quote timestamps while converting window keys', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { summary: { WAIT: 1, CONFIRMED: 0, FAILED: 0, total: 1 },
      items: [{ confirmation_score: null, available_score_weight: 0, chase_risk: 'UNKNOWN', metrics: { return_5m: .01, return_15m: null, quote_time: '2026-09-21T13:35:00Z' } }] } });
    const result = await api.read('US', 'WAIT', 'trend');
    expect(result.summary.wait).toBe(1);
    expect(result.items[0]?.confirmationScore).toBeNull();
    expect(result.items[0]?.availableScoreWeight).toBe(0);
    expect(result.items[0]?.chaseRisk).toBe('UNKNOWN');
    expect(result.items[0]?.metrics).toEqual({ return5M: .01, return15M: null, quoteTime: '2026-09-21T13:35:00Z' });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/intraday-confirmation', { params: { market: 'US', state: 'WAIT', candidate_source: 'trend' } });
  });
  it('passes historical dates and cancellation while preserving the frozen baseline and blank returns', async () => {
    const signal = new AbortController().signal;
    const item = { first_confirmed_price: 101.25, first_confirmed_quote_time: '2026-09-21T13:35:00Z', return_3d: .05, return_5d: 0, return_10d: null };
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { items: [item] } });
    const result = await api.read('CN', undefined, undefined, '2026-09-21', signal);
    expect(result.items[0]).toEqual({ firstConfirmedPrice: 101.25, firstConfirmedQuoteTime: '2026-09-21T13:35:00Z', return3D: .05, return5D: 0, return10D: null });
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/intraday-confirmation', { params: { market: 'CN', state: undefined, candidate_source: undefined, trade_date: '2026-09-21' }, signal });
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: item });
    expect(await api.detail('600001.SH', 'CN', '2026-09-21', signal)).toEqual(result.items[0]);
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/intraday-confirmation/600001.SH', { params: { market: 'CN', trade_date: '2026-09-21' }, signal });
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { dates: ['2026-09-21', '2026-09-18'] } });
    expect(await api.dates('CN', signal)).toEqual({ dates: ['2026-09-21', '2026-09-18'] });
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/intraday-confirmation/dates', { params: { market: 'CN' }, signal });
  });
  it('only enqueues computation on explicit POST', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { task_id: 'job' } });
    expect(await api.run('CN')).toEqual({ taskId: 'job' });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/intraday-confirmation/run', { market: 'CN' });
  });
});
