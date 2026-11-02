import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { confluenceApi, type ConfluenceItem, type ConfluenceSignal } from '@/api/confluence';
import type { Confirmation } from '@/api/intradayConfirmation';
import IntradaySourceEvidence from '../IntradaySourceEvidence.vue';

vi.mock('@/api/confluence', () => ({ confluenceApi: { detail: vi.fn() } }));
const generatedAt = '2026-10-30T12:30:00Z';
const confirmation: Confirmation = {
  code: 'TEST.US', name: '测试', candidateSource: 'trend', candidateSources: ['trend', 'confluence'],
  candidateTradeDate: '2026-10-30', candidateReason: ['昨日趋势入选'], sourceGeneratedAt: '2026-10-30T12:40:00Z',
  sourceEvidence: [
    { source: 'confluence', tradeDate: '2026-10-30', generatedAt, rank: null, reasons: ['昨日共振入选'] },
    { source: 'trend', tradeDate: '2026-10-30', generatedAt: '2026-10-30T12:40:00Z', rank: 3, reasons: ['昨日趋势入选'] },
  ],
  state: 'CONFIRMED', confirmationScore: 90, availableScoreWeight: 100, chaseRisk: 'LOW', reasons: [],
  stateReasons: [], metrics: {}, trend: {}, firstConfirmedAt: null, failedAt: null, generatedAt: null, currentPriceRecovered: false,
};
const available: ConfluenceSignal = { sourceModule: 'test', status: 'positive', weight: 30, score: 24,
  strength: 80, normalizedWeight: 60, contribution: 48, tradeDate: '2026-10-30', sourceGeneratedAt: generatedAt, evidence: {}, reasons: [] };
const item: ConfluenceItem = {
  instrumentId: 1, code: 'TEST.US', name: '测试', confluenceScore: 72, availableWeight: 50,
  availableSignalCount: 2, positiveSignalCount: 1, eligible: true, strongConfluence: false,
  signals: { trend: { ...available }, etf: { ...available, status: 'neutral', strength: 0, score: 0, contribution: 0 } } as ConfluenceItem['signals'],
  reasons: [], generatedAt,
};
const response = { market: 'US' as const, tradeDate: '2026-10-30', algorithmVersion: 'confluence_v2_2', item };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(confluenceApi.detail).mockResolvedValue(response); });

describe('frozen intraday selection sources', () => {
  it('highlights every source and reads the exact prior-session confluence generation', async () => {
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation, market: 'US' } });
    await flushPromises();
    expect(confluenceApi.detail).toHaveBeenCalledWith('TEST.US', 'US', '2026-10-30', expect.any(AbortSignal));
    expect(wrapper.text()).toContain('共振精选'); expect(wrapper.text()).toContain('趋势前30');
    expect(wrapper.text()).toContain('正式综合排名第 3 名');
    expect(wrapper.get('[data-testid="intraday-confluence-total"]').text()).toContain('72.00');
    expect(wrapper.get('[data-testid="intraday-confluence-trend"]').text()).toContain('80.0');
    expect(wrapper.get('[data-testid="intraday-confluence-trend"]').text()).toContain('48.00');
    expect(wrapper.get('[data-testid="intraday-confluence-etf"]').text()).toContain('0.0');
    expect(wrapper.get('[data-testid="intraday-confluence-options"]').text()).toContain('缺失');
    expect(wrapper.get('[data-testid="intraday-confluence-options"]').text()).toContain('—');
    expect(wrapper.get('[data-testid="intraday-confluence-options"]').text()).not.toContain('0.0');
    wrapper.unmount();
  });
  it.each([
    { ...response, tradeDate: '2026-11-02' },
    { ...response, market: 'CN' as const },
    { ...response, item: { ...item, code: 'OTHER.US' } },
    { ...response, item: { ...item, generatedAt: '2026-10-30T20:00:00Z' } },
  ])('does not substitute another date, market, security or rerun for frozen evidence', async value => {
    vi.mocked(confluenceApi.detail).mockResolvedValue(value);
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation, market: 'US' } }); await flushPromises();
    expect(wrapper.find('[data-testid="intraday-confluence-total"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('无法展示冻结选股时的原始分数'); wrapper.unmount();
  });
  it('supports a legacy primary confluence source and the original weighted-score format', async () => {
    vi.mocked(confluenceApi.detail).mockResolvedValue({ ...response, algorithmVersion: 'confluence_v1', item: {
      ...item, signals: { trend: { ...available, strength: undefined, contribution: undefined } } as ConfluenceItem['signals'],
    } });
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation: {
      ...confirmation, candidateSource: 'confluence', candidateSources: undefined, sourceEvidence: undefined, sourceGeneratedAt: generatedAt,
    }, market: 'US' } }); await flushPromises();
    expect(wrapper.get('[data-testid="intraday-confluence-trend"]').text()).toContain('80.0');
    expect(wrapper.get('[data-testid="intraday-confluence-trend"]').text()).toContain('48.00');
    expect(wrapper.text()).toContain('宏观环境'); wrapper.unmount();
  });
  it('does not fetch confluence for trend-only candidates or an unverifiable secondary legacy source', async () => {
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation: {
      ...confirmation, candidateSources: ['trend'], sourceEvidence: undefined,
    }, market: 'US' } }); await flushPromises();
    expect(confluenceApi.detail).not.toHaveBeenCalled();
    await wrapper.setProps({ confirmation: { ...confirmation, sourceEvidence: undefined } }); await flushPromises();
    expect(confluenceApi.detail).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('历史记录未保存共振批次'); wrapper.unmount();
  });
  it('isolates source failures and allows retry without replacing the candidate', async () => {
    vi.mocked(confluenceApi.detail).mockRejectedValueOnce(new Error('offline'));
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation, market: 'US' } }); await flushPromises();
    expect(wrapper.text()).toContain('趋势前30'); expect(wrapper.text()).toContain('重试共振分数');
    await wrapper.findAll('button').find(b => b.text().includes('重试共振分数'))!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('72.00'); wrapper.unmount();
  });
  it('cancels and discards old confluence requests when changing securities or closing', async () => {
    const old = deferred<typeof response>(); vi.mocked(confluenceApi.detail).mockReturnValueOnce(old.promise);
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation, market: 'US' } });
    const oldSignal = vi.mocked(confluenceApi.detail).mock.calls[0]![3]!;
    vi.mocked(confluenceApi.detail).mockResolvedValue({ ...response, item: { ...item, code: 'NEW.US', confluenceScore: 81 } });
    await wrapper.setProps({ confirmation: { ...confirmation, code: 'NEW.US' } }); await flushPromises();
    expect(oldSignal.aborted).toBe(true);
    old.resolve(response); await flushPromises();
    expect(wrapper.get('[data-testid="intraday-confluence-total"]').text()).toContain('81.00');
    const lastSignal = vi.mocked(confluenceApi.detail).mock.calls.at(-1)![3]!;
    wrapper.unmount(); expect(lastSignal.aborted).toBe(true);
  });
  it('keeps removed historical confluence scores absent', async () => {
    vi.mocked(confluenceApi.detail).mockRejectedValue({ response: { status: 404, data: { detail: 'missing' } } });
    const wrapper = mount(IntradaySourceEvidence, { props: { confirmation, market: 'US' } }); await flushPromises();
    expect(wrapper.text()).toContain('原始分数暂缺'); expect(wrapper.find('button').exists()).toBe(false); wrapper.unmount();
  });
});
