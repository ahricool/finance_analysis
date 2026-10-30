import { useMarketStore } from '@/stores/marketStore';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import SignalCenterPage from '../SignalCenterPage.vue';
import { signalCenterApi as api, type SignalDetail } from '@/api/signalCenter';
vi.mock('@/api/signalCenter', () => ({ signalCenterApi: { daily: vi.fn(), history: vi.fn(), detail: vi.fn() } }));
const signal: SignalDetail = { market: 'CN', signalDate: '2026-09-22', status: 'completed', selectedSymbol: null,
  decision: 'NO_TRADE', confidence: 'medium', createdAt: '2026-09-22T12:00:00Z', completedAt: '2026-09-22T12:01:00Z',
  analysis: { thesis: '冲突明显，不交易', positiveSignals: [], risks: ['追高'], invalidations: [] },
  candidateSnapshot: { capturedAt: '2026-09-22T12:00:00Z', candidates: [{ symbol: '600000.SH' }], sourceAvailability: { trend: { status: 'available', dataAsOf: '2026-09-22', generatedAt: '2026-09-22T11:00:00Z' } } },
  model: 'test', promptVersion: 'v1', error: null };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.daily).mockResolvedValue({ items: [signal], requestedDates: { CN: '2026-09-22', US: '2026-09-21' } }); vi.mocked(api.history).mockResolvedValue([signal]); vi.mocked(api.detail).mockResolvedValue(signal); });
describe('Signal Center page', () => {
  it('shows NO_TRADE distinctly from a missing market and uses persisted historical detail', async () => {
    const wrapper = mount(SignalCenterPage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(wrapper.text()).toContain('当日不交易');
    expect(wrapper.text()).not.toContain('美股 · 2026-09-21');
    useMarketStore().market = 'US';
    await flushPromises();
    expect(api.daily).toHaveBeenLastCalledWith(undefined, 'US');
    expect(api.history).toHaveBeenLastCalledWith(0, 'US');
    expect(wrapper.text()).toContain('当日尚无信号记录');
    useMarketStore().market = 'CN';
    await flushPromises();
    expect(wrapper.text()).toContain('冲突明显，不交易');
    await wrapper.get('[aria-label="查看 2026-09-22 CN 信号"]').trigger('click');
    await flushPromises();
    expect(api.detail).toHaveBeenCalledWith('CN', '2026-09-22');
    wrapper.unmount();
  });
  it.each(['浦发银行', null])('shows stock name and code with missing-name fallback: %s', async (selectedName) => {
    const buy: SignalDetail = { ...signal, decision: 'BUY', selectedSymbol: '600000.SH', selectedName };
    vi.mocked(api.daily).mockResolvedValue({ items: [buy], requestedDates: { CN: '2026-09-22', US: '2026-09-21' } });
    vi.mocked(api.history).mockResolvedValue([buy]);
    vi.mocked(api.detail).mockResolvedValue(buy);
    const wrapper = mount(SignalCenterPage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    const label = `600000.SH - ${selectedName || '名称暂缺'}`;
    expect(wrapper.get('[data-testid="signal-card"] .stock-identity').text()).toBe(label);
    expect(wrapper.get('tbody').text()).toContain(label);
    await wrapper.get('[aria-label="查看 2026-09-22 CN 信号"]').trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain(label);
    wrapper.unmount();
  });
  it('uses the date picker with weekends disabled and reloads the selected day', async () => {
    const wrapper = mount(SignalCenterPage, { global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(wrapper.find('input[type="date"]').exists()).toBe(false);
    const picker = wrapper.getComponent(AppDatePicker);
    expect(picker.props('disableWeekends')).toBe(true);
    picker.vm.$emit('update:modelValue', '2026-09-25');
    await flushPromises();
    expect(api.daily).toHaveBeenLastCalledWith('2026-09-25', 'CN');
    wrapper.unmount();
  });
  it('displays failure without presenting it as NO_TRADE', async () => {
    vi.mocked(api.daily).mockResolvedValue({ items: [{ ...signal, status: 'failed', decision: null, confidence: null, analysis: null }], requestedDates: { CN: '2026-09-22', US: '2026-09-21' } });
    vi.mocked(api.history).mockResolvedValue([]);
    const wrapper = mount(SignalCenterPage, { global: { plugins: [createPinia()] } }); await flushPromises();
    expect(wrapper.text()).toContain('分析失败，未产生信号');
    expect(wrapper.text()).not.toContain('当日不交易');
    wrapper.unmount();
  });
});

it('renders all three picks including ETF with separate evidence and returns', async () => {
  const recommendations = ['600000.SH', '510300.SH', '600001.SH'].map((symbol, index) => ({
    symbol, name: ['浦发银行', '沪深300ETF', '测试股票'][index], instrumentType: index === 1 ? 'ETF' : 'STOCK',
    confidence: 'medium', thesis: `推荐依据${index}`, positiveSignals: ['趋势改善'], risks: ['价格波动'],
    invalidations: ['跌破结构'], evidence: [{ field: `${symbol}.trends.20.rank`, value: index + 1, dataAsOf: signal.signalDate, interpretation: '趋势排名靠前' }],
    externalSources: [{ url: 'https://example.com/announcement', title: '公司公告', publishedDate: signal.signalDate, excerpt: '公告原始信息' }],
    evaluation: { method: 'next_session_open_v1', status: 'partial' as const, reason: null, entryDate: '2026-09-23', entryPrice: 100,
      asOf: '2026-09-23', observedSessions: 1, missingDates: [], horizons: [{ days: 1, targetDate: '2026-09-23', status: 'available' as const, value: [.1, -.05, .02][index]! }],
      mfe: .1, mae: -.05, maxDrawdownClose: -.03, evaluatedAt: '2026-09-23T12:00:00Z' },
  }));
  const multi: SignalDetail = { ...signal, decision: 'BUY', selectedSymbol: '600000.SH', recommendations, searchEvidence: { status: 'confirmed' } };
  vi.mocked(api.daily).mockResolvedValue({ items: [multi], requestedDates: { CN: signal.signalDate, US: signal.signalDate } });
  vi.mocked(api.history).mockResolvedValue([multi]);
  const wrapper = mount(SignalCenterPage, { global: { plugins: [createPinia()] } });
  await flushPromises();
  expect(wrapper.findAll('[data-testid="signal-pick"]')).toHaveLength(3);
  expect(wrapper.text()).toContain('沪深300ETF');
  expect(wrapper.text()).toContain('3 个精选信号');
  expect(wrapper.text()).toContain('核验证据');
  const rows = wrapper.get('tbody').text();
  expect(rows).toContain('+10.00%'); expect(rows).toContain('-5.00%'); expect(rows).toContain('+2.00%');
  expect(wrapper.find('a[href="https://example.com/announcement"]').attributes('rel')).toBe('noopener noreferrer');
  wrapper.unmount();
});
