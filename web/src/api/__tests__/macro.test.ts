import { describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { getMacroDashboard, getMacroSeries } from '../macro';
vi.mock('../index', () => ({ default: { get: vi.fn() } }));
describe('macro API boundary', () => {
  it('converts nested snake_case including numbered returns and preserves null', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { trade_date: '2026-09-11', risk_score: null, instruments: [{ ret_1d: 0.01, ret_5d: -0.02, ret_20d: null }], data_quality: { stale_symbols: ['VIX.US'] } } });
    expect(await getMacroDashboard({ asOf: '2026-09-12' })).toEqual({ tradeDate: '2026-09-11', riskScore: null, instruments: [{ ret1D: 0.01, ret5D: -0.02, ret20D: null }], dataQuality: { staleSymbols: ['VIX.US'] } });
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/macro/dashboard', { params: { as_of: '2026-09-12' } });
  });
  it('serializes CSV selectors and as_of without changing normalized points', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { series: [{ points: [{ date: '2026-09-11', value: 108.7 }] }] } });
    const result = await getMacroSeries({ range: '60d', mode: 'normalized', symbols: ['SPY.US', 'QQQ.US'], series: ['HYG_LQD', 'IWM_SPY'], asOf: '2026-09-12' });
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/macro/series', { params: { range: '60d', mode: 'normalized', symbols: 'SPY.US,QQQ.US', series: 'HYG_LQD,IWM_SPY', as_of: '2026-09-12' } });
    expect(result.series[0]!.points[0]!.value).toBe(108.7);
  });
});
