import MetricHint from '@/components/app/MetricHint.vue';
import { metricHint } from '@/utils/metricHints';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { confluenceApi, type ConfluenceRanking } from '@/api/confluence';
import { intradayConfirmationApi, type Confirmation } from '@/api/intradayConfirmation';
import { dragonTigerFlowApi, type FlowOverview } from '@/api/dragonTigerFlow';
import { quantApi } from '@/api/quant';
import type { QuantSignal } from '@/types/quant';
import { toCamelCase } from '@/api/utils';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ConfluenceDetailPanel from '../ConfluenceDetailPanel.vue';
import IntradayDetailPanel from '../IntradayDetailPanel.vue';
import DragonTigerDetailPanel from '../DragonTigerDetailPanel.vue';
import QuantDetailPanel from '../QuantDetailPanel.vue';
import confluenceFixture from '../../../../../e2e/fixtures/confluence';
import flowFixture from '../../../../../e2e/fixtures/dragonTigerFlow';

vi.mock('@/api/confluence', () => ({ confluenceApi: { detail: vi.fn(), dates: vi.fn() } }));
vi.mock('@/api/intradayConfirmation', () => ({ intradayConfirmationApi: { detail: vi.fn() } }));
vi.mock('@/api/quant', () => ({ quantApi: { signal: vi.fn(), signalHistory: vi.fn() } }));
vi.mock('@/api/dragonTigerFlow', async original => ({ ...await original<typeof import('@/api/dragonTigerFlow')>(), dragonTigerFlowApi: { overview: vi.fn() } }));
const ranking = toCamelCase<ConfluenceRanking>(confluenceFixture);
const flow = toCamelCase<FlowOverview>(flowFixture);
const signal: QuantSignal = { market: 'US', modelVersion: 'v1', finalScore: 80, marketScore: 70, crossSectionScore: 60, timeSeriesScore: 50, riskPenalty: 1, predictedReturn: .1, signal: 'BUY', universeRank: 1, id: 1, code: 'AAPL.US', name: 'Apple', tradeDate: '2026-09-21', reasons: ['量化依据'], scoreComponents: { alpha: .8 } };
const confirmation: Confirmation = { candidateSource: 'trend', sourceGeneratedAt: '2026-09-18T12:00:00Z', confirmationScore: 70, availableScoreWeight: 80, firstConfirmedAt: null, failedAt: '2026-09-21T13:00:00Z', generatedAt: '2026-09-21T14:00:00Z', code: 'AAPL.US', name: 'Apple', candidateTradeDate: '2026-09-18', candidateReason: ['昨日候选'],
  state: 'FAILED', chaseRisk: 'HIGH', reasons: [{ code: 'vwap', text: '价格低于 VWAP' }], stateReasons: [{ code: 'failed', text: '状态依据' }],
  currentPriceRecovered: true, metrics: { gapPct: .01, volumeRatio: 1.2 }, trend: { officialTrendState: 'UP', temporaryTrendState: 'WEAK' } };
const stubs = { DailyKLineCard: true };
const missing = { response: { status: 404, data: { detail: 'missing' } } };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(confluenceApi.dates).mockResolvedValue(['2026-09-21', '2026-09-22']);
  vi.mocked(confluenceApi.detail).mockResolvedValue({ market: 'CN', tradeDate: '2026-09-22', algorithmVersion: 'v1', item: ranking.items[0]! });
  vi.mocked(intradayConfirmationApi.detail).mockResolvedValue(confirmation);
  vi.mocked(dragonTigerFlowApi.overview).mockResolvedValue(flow);
  vi.mocked(quantApi.signal).mockResolvedValue(signal);
  vi.mocked(quantApi.signalHistory).mockResolvedValue([{ ...signal, id: 2, tradeDate: '2026-09-18' }]);
});
describe('independent research detail panels', () => {
  it('loads confluence from symbol and latest persisted date without an originating ranking', async () => {
    const wrapper = mount(ConfluenceDetailPanel, { props: { symbol: '600001.SH', market: 'CN' }, global: { stubs } });
    await flushPromises();
    expect(confluenceApi.detail).toHaveBeenCalledWith('600001.SH', 'CN', '2026-09-22');
    expect(wrapper.text()).toContain('各来源以独立日期为准');
    expect(wrapper.text()).toContain('Why Confluence');
    const chart = wrapper.getComponent(DailyKLineCard);
    expect(chart.props('highlightDate')).toBe('2026-09-22');
    expect(chart.props('endDate')).toBeUndefined();
    wrapper.unmount();
  });
  it('uses explicit historical confluence dates and ignores an older symbol result', async () => {
    const old = deferred<Awaited<ReturnType<typeof confluenceApi.detail>>>();
    vi.mocked(confluenceApi.detail).mockReturnValueOnce(old.promise);
    const wrapper = mount(ConfluenceDetailPanel, { props: { symbol: 'OLD.US', market: 'US', context: { tradeDate: '2026-09-18', view: 'preview' } }, global: { stubs } });
    await wrapper.setProps({ symbol: 'NEW.US' }); await flushPromises();
    expect(confluenceApi.dates).not.toHaveBeenCalled();
    expect(confluenceApi.detail).toHaveBeenLastCalledWith('NEW.US', 'US', '2026-09-18');
    old.resolve({ market: 'US', tradeDate: '1999-01-01', algorithmVersion: 'stale', item: ranking.items[0]! });
    await flushPromises();
    expect(wrapper.text()).not.toContain('stale');
    expect(wrapper.text()).toContain('正式共振快照');
    wrapper.unmount();
  });
  it('presents latest intraday semantics, frozen logic and sticky failure evidence', async () => {
    const wrapper = mount(IntradayDetailPanel, { props: { symbol: 'AAPL.US', market: 'US', context: { tradeDate: '2025-01-01' } } });
    await flushPromises();
    expect(intradayConfirmationApi.detail).toHaveBeenCalledWith('AAPL.US', 'US');
    for (const text of ['不支持历史回放', '2025-01-01', '昨日候选', 'FAILED', 'HIGH', '状态依据', '不自动恢复', 'unavailable']) expect(wrapper.text()).toContain(text);
    wrapper.unmount();
  });
  it('passes all dragon tiger observation filters and preserves the source concept', async () => {
    const filters = { endDate: '2026-09-21', days: 5, board: 'org', rangeDays: 1 } as const;
    const wrapper = mount(DragonTigerDetailPanel, { props: { symbol: '600001.SH', market: 'CN', context: { dragonTiger: filters, dragonTigerConceptId: 'concept-2' } } });
    await flushPromises();
    expect(dragonTigerFlowApi.overview).toHaveBeenCalledWith(filters);
    expect(wrapper.get('select').element.value).toBe('concept-2');
    expect(wrapper.text()).toContain('1/2');
    expect(wrapper.text()).toContain('不代表游资净额为零');
    await wrapper.get('select').setValue('concept-0');
    expect(wrapper.get('select').element.value).toBe('concept-0');
    wrapper.unmount();
  });
  it('defaults dragon tiger to the source trade date and keeps 3-day snapshots non-cumulative', async () => {
    const wrapper = mount(DragonTigerDetailPanel, { props: { symbol: '600001.SH', market: 'CN', context: { tradeDate: '2026-09-18' } } });
    await flushPromises();
    expect(dragonTigerFlowApi.overview).toHaveBeenCalledWith({ endDate: '2026-09-18', days: 1, board: 'all', rangeDays: 1 });
    await wrapper.setProps({ context: { dragonTiger: { endDate: '2026-09-21', days: 20, board: 'hot_money', rangeDays: 3 } } });
    await flushPromises();
    expect(wrapper.text()).toContain('3日榜独立截面，不累计');
    wrapper.unmount();
  });
  it('preserves quant historical signal, date-bounded history, scores and chart highlight', async () => {
    const wrapper = mount(QuantDetailPanel, { props: { symbol: 'AAPL.US', market: 'US', context: { tradeDate: '2026-09-21' } }, global: { stubs } });
    await flushPromises();
    expect(quantApi.signal).toHaveBeenCalledWith('AAPL.US', 'US', '2026-09-21');
    expect(quantApi.signalHistory).toHaveBeenCalledWith('AAPL.US', 'US', '2026-09-21');
    for (const text of ['量化依据', '风险惩罚', '横截面', '时间序列', '2026-09-18', 'alpha']) expect(wrapper.text()).toContain(text);
    expect(wrapper.getComponent(DailyKLineCard).props('highlightDate')).toBe('2026-09-21');
    expect(wrapper.getComponent(DailyKLineCard).props('endDate')).toBeUndefined();
    wrapper.unmount();
  });
  it('clears prior quant data on symbol changes and ignores late requests', async () => {
    const old = deferred<QuantSignal>(); vi.mocked(quantApi.signal).mockReturnValueOnce(old.promise);
    const wrapper = mount(QuantDetailPanel, { props: { symbol: 'OLD.US', market: 'US' }, global: { stubs } });
    await wrapper.setProps({ symbol: 'AAPL.US' }); await flushPromises();
    old.resolve({ ...signal, reasons: ['stale result'] }); await flushPromises();
    expect(wrapper.text()).not.toContain('stale result'); expect(wrapper.text()).toContain('量化依据');
    wrapper.unmount();
  });
  it.each([ConfluenceDetailPanel, IntradayDetailPanel, DragonTigerDetailPanel, QuantDetailPanel])('handles HK without issuing unsupported requests', async component => {
    const wrapper = mount(component, { props: { symbol: '00700.HK', market: 'HK' }, global: { stubs } });
    await flushPromises();
    expect(confluenceApi.dates).not.toHaveBeenCalled(); expect(confluenceApi.detail).not.toHaveBeenCalled();
    expect(intradayConfirmationApi.detail).not.toHaveBeenCalled(); expect(dragonTigerFlowApi.overview).not.toHaveBeenCalled(); expect(quantApi.signal).not.toHaveBeenCalled();
    expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(false); wrapper.unmount();
  });
  it('treats absent snapshots neutrally and offers retry only for actual request failures', async () => {
    vi.mocked(quantApi.signal).mockRejectedValueOnce(missing);
    const wrapper = mount(QuantDetailPanel, { props: { symbol: 'AAPL.US', market: 'US' }, global: { stubs } });
    await flushPromises(); expect(wrapper.text()).toContain('暂无正式量化信号'); expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(false);
    vi.mocked(quantApi.signal).mockRejectedValueOnce(new Error('offline'));
    await wrapper.setProps({ symbol: 'OTHER.US' }); await flushPromises();
    expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(true);
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('量化依据'); wrapper.unmount();
  });
  it('does not start a confluence detail fetch after disposal during date discovery', async () => {
    const dates = deferred<string[]>(); vi.mocked(confluenceApi.dates).mockReturnValueOnce(dates.promise);
    const wrapper = mount(ConfluenceDetailPanel, { props: { symbol: '600001.SH', market: 'CN' }, global: { stubs } });
    wrapper.unmount(); dates.resolve(['2026-09-22']); await flushPromises();
    expect(confluenceApi.detail).not.toHaveBeenCalled();
  });
  it('invalidates intraday evidence when switching market before an old response arrives', async () => {
    const old = deferred<Confirmation>(); vi.mocked(intradayConfirmationApi.detail).mockReturnValueOnce(old.promise);
    const wrapper = mount(IntradayDetailPanel, { props: { symbol: 'AAPL.US', market: 'US' } });
    await wrapper.setProps({ symbol: '600001.SH', market: 'CN' }); await flushPromises();
    expect(intradayConfirmationApi.detail).toHaveBeenLastCalledWith('600001.SH', 'CN');
    old.resolve({ ...confirmation, candidateReason: ['stale intraday'] }); await flushPromises();
    expect(wrapper.text()).not.toContain('stale intraday'); expect(wrapper.text()).toContain('昨日候选');
    wrapper.unmount();
  });
  it('discards old dragon tiger filter results and displays neutral missing evidence', async () => {
    const old = deferred<FlowOverview>(); vi.mocked(dragonTigerFlowApi.overview).mockReturnValueOnce(old.promise);
    const wrapper = mount(DragonTigerDetailPanel, { props: { symbol: '600001.SH', market: 'CN' } });
    vi.mocked(dragonTigerFlowApi.overview).mockResolvedValueOnce({ ...flow, evidence: [], hotMoneyDetails: [] });
    await wrapper.setProps({ context: { dragonTiger: { endDate: '2026-09-18', board: 'hot_money', days: 1, rangeDays: 3 } } }); await flushPromises();
    old.resolve(flow); await flushPromises();
    expect(wrapper.text()).toContain('暂无上榜证据'); expect(wrapper.find('table').exists()).toBe(false);
    wrapper.unmount();
  });
  it('renders missing confluence, intraday and flow snapshots without request-error alerts', async () => {
    vi.mocked(confluenceApi.detail).mockRejectedValue(missing);
    vi.mocked(intradayConfirmationApi.detail).mockRejectedValue(missing);
    vi.mocked(dragonTigerFlowApi.overview).mockRejectedValue(missing);
    for (const component of [ConfluenceDetailPanel, IntradayDetailPanel, DragonTigerDetailPanel]) {
      const wrapper = mount(component, { props: { symbol: '600001.SH', market: 'CN', context: { tradeDate: '2026-09-21' } }, global: { stubs } });
      await flushPromises(); expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(false); expect(wrapper.text()).toContain('暂无'); wrapper.unmount();
    }
  });

});


describe('preserved metric hints after detail extraction', () => {
  it('keeps all five quant score explanations scoped to quant', async () => {
    const wrapper = mount(QuantDetailPanel, { props: { symbol: 'AAPL.US', market: 'US' }, global: { stubs } });
    await flushPromises();
    expect(wrapper.findAllComponents(MetricHint).map(hint => hint.props('description'))).toEqual(
      ['最终得分', '风险惩罚', '市场', '横截面', '时间序列'].map(label => metricHint('quant', label)),
    );
    wrapper.unmount();
  });
  it('keeps confluence source-field explanations instead of ambiguous display-label lookups', async () => {
    const wrapper = mount(ConfluenceDetailPanel, { props: { symbol: '600001.SH', market: 'CN' }, global: { stubs } });
    await flushPromises();
    const descriptions = wrapper.findAllComponents(MetricHint).map(hint => hint.props('description'));
    for (const [scope, field] of [['confluence-industry', 'strengthScore'], ['confluence-trend', 'state'], ['confluence-quant', 'finalScore']]) {
      const expected = metricHint(scope, field!);
      expect(expected).toBeTruthy();
      expect(descriptions).toContain(expected);
    }
    wrapper.unmount();
  });
  it('keeps distinct whole-stock, selected-source and concept-weight explanations', async () => {
    const wrapper = mount(DragonTigerDetailPanel, { props: { symbol: '600001.SH', market: 'CN' } });
    await flushPromises();
    const descriptions = wrapper.findAllComponents(MetricHint).map(hint => hint.props('description'));
    for (const label of ['股票整体净额', '所选口径原始净额', '当日概念 / 每概念权重']) {
      expect(descriptions).toContain(metricHint('flow', label));
    }
    wrapper.unmount();
  });
});
