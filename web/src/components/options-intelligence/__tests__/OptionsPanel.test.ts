import { describe, it, expect, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import OptionsPanel from '../OptionsPanel.vue';
import { optionsIntelligenceApi } from '@/api/optionsIntelligence';
import { tasksApi } from '@/api/tasks';
vi.mock('@/api/optionsIntelligence', () => ({ optionsIntelligenceApi: { detail: vi.fn(), refresh: vi.fn() } }));
vi.mock('@/api/tasks', () => ({ tasksApi: { getTaskRunDetail: vi.fn() } }));
const mock = vi.mocked(optionsIntelligenceApi.detail);
const score = { value: null, method: 'initial_absolute_rules', confidence: 'low', evidenceCount: 0, reason: 'insufficient_protection_demand_evidence' };
const stubs = { OptionsCharts: true, RouterLink: true };
describe('OptionsPanel', () => {
  it('keeps missing scores as N/A and shows source/time limitations', async () => {
    mock.mockResolvedValue({ symbol: 'AAPL.US', latest: { symbol: 'AAPL.US', status: 'warming_up',
      scores: { bearishDemand: score, unusualActivity: score, liquidityRisk: score }, evidenceGrade: 'C',
      historyDays: 0, ivSampleCount: 0, limitations: ['quote_timestamp_unknown', 'oi_as_of_unknown'],
      contracts: [], events: [], termStructure: [], skewTerms: [] }, dailyHistory: [], events: [], analyses: [], reason: null });
    const wrapper = mount(OptionsPanel, { props: { symbol: 'AAPL.US' }, global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('N/A');
    expect(wrapper.text()).toContain('证据 C');
    expect(wrapper.text()).toContain('OI 数据日期未知');
    expect(wrapper.text()).toContain('报价时间未知');
    expect(mock).toHaveBeenCalledWith('AAPL.US');
    wrapper.unmount();
  });
  it('clears stale results when switching symbols', async () => {
    mock.mockResolvedValue({ symbol: 'AAPL.US', latest: null, dailyHistory: [], events: [], analyses: [], reason: '尚未采集 AAPL' });
    const wrapper = mount(OptionsPanel, { props: { symbol: 'AAPL.US' }, global: { stubs } });
    await flushPromises();
    mock.mockResolvedValue({ symbol: 'MSFT.US', latest: null, dailyHistory: [], events: [], analyses: [], reason: '尚未采集 MSFT' });
    await wrapper.setProps({ symbol: 'MSFT.US' }); await flushPromises();
    expect(wrapper.text()).toContain('尚未采集 MSFT');
    expect(wrapper.text()).not.toContain('尚未采集 AAPL');
    wrapper.unmount();
  });
  it('moves expiry selection to the available chain after a refresh', async () => {
    const detail = (expiration: string, symbol: string) => ({ symbol: 'AAPL.US', latest: {
      symbol: 'AAPL.US', status: 'warming_up', scores: { bearishDemand: score, unusualActivity: score, liquidityRisk: score },
      contracts: [{ symbol, expiration, optionType: 'put', strike: 100, multiplier: 100, bid: 2, ask: 3,
        bidSize: null, askSize: null, volume: 100, openInterest: 100, oiDate: null, iv: null,
        delta: null, gamma: null, theta: null, vega: null, spread: 0.4, volumeOi: 1,
        quoteStatus: 'quote_timestamp_unknown', quoteTimestamp: null, dataSource: 'yfinance', feedType: 'delayed',
        observedAt: '', notes: [], limitations: [], risk: score, volumePercentile: null, baselineDays: 0,
        premiumEstimate: null, premiumVolume: null, events: [] }], limitations: [], events: [], termStructure: [], skewTerms: [],
    }, dailyHistory: [], events: [], analyses: [], reason: null });
    mock.mockResolvedValueOnce(detail('2026-10-09', 'AAPL261009P00100000'))
      .mockResolvedValueOnce(detail('2026-10-16', 'AAPL261016P00100000'));
    vi.mocked(optionsIntelligenceApi.refresh).mockResolvedValue({ taskId: 'refresh-task', status: 'pending' });
    vi.mocked(tasksApi.getTaskRunDetail).mockResolvedValue({ status: 'completed' } as Awaited<ReturnType<typeof tasksApi.getTaskRunDetail>>);
    const wrapper = mount(OptionsPanel, { props: { symbol: 'AAPL.US' }, global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('AAPL261009P00100000');
    await wrapper.findAll('button').find(b => b.text().includes('刷新期权链'))!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('AAPL261016P00100000');
    expect(wrapper.text()).not.toContain('AAPL261009P00100000');
    wrapper.unmount();
  });
});
