import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getMacroDashboard, getMacroSeries, type MacroDashboard, type MacroSeriesResult } from '@/api/macro';
import MacroPage from '@/pages/market/MacroPage.vue';
import MacroStateCards from '../MacroStateCards.vue';
import MacroPerformanceChart from '../MacroPerformanceChart.vue';
import MacroSeriesChart from '../MacroSeriesChart.vue';
import { createPinia, setActivePinia } from 'pinia';
import { theme, systemPrefersDark } from '@/composables/useTheme';
import { defaultAssets, ratioKeys } from '../display';
vi.mock('@/api/macro', () => ({ getMacroDashboard: vi.fn(), getMacroSeries: vi.fn() }));
vi.mock('vue-echarts', () => ({ default: { name: 'VChart', props: ['option', 'autoresize'], template: '<div />' } }));
enableAutoUnmount(afterEach);
const quality = { expected: 13, available: 11, coverage: 11 / 13, missingSymbols: ['UUP.US'], staleSymbols: ['VIX.US'], insufficientHistorySymbols: ['TLT.US'], partial: true };
const metrics = { tradeDate: '2026-09-11', ret1D: 0.0011, ret5D: -0.0146, ret20D: null, trend: 'DOWN' as const };
function dashboard(): MacroDashboard {
  return { tradeDate: '2026-09-11', generatedAt: '2026-09-12T00:00:00Z', regime: 'RISK_ON', riskScore: 72, signalCoverage: 0.85,
    states: { rates: 'EASING', credit: 'HEALTHY', dollar: 'STRONG', volatility: 'CALM' }, dataQuality: quality,
    instruments: [{ ...metrics, code: 'TLT.US', name: 'Long Treasury', category: 'RATES', close: 80.87 }],
    ratios: [{ ...metrics, key: 'HYG_LQD', name: 'Credit', value: 0.754, signal: null, partial: true }],
    signals: [{ key: 'VIX.US', riskOnTrend: 'DOWN', trend: 'DOWN', weight: 20, contribution: null }],
  };
}
function series(value = 105.2): MacroSeriesResult {
  return { range: '60d', mode: 'normalized', benchmark: null, tradeDate: '2026-09-11', dataQuality: quality,
    series: [{ key: 'SPY.US', code: 'SPY.US', name: 'SPY', category: 'EQUITY', partial: true, points: [{ date: '2026-09-08', value: 100 }, { date: '2026-09-11', value }] }],
  };
}
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); vi.mocked(getMacroDashboard).mockResolvedValue(dashboard()); vi.mocked(getMacroSeries).mockResolvedValue(series()); });
afterEach(() => { theme.value = 'light'; document.documentElement.removeAttribute('style'); });
describe('Macro dashboard', () => {
  it('renders regime, score, states, quality and both tables with return units and nulls', async () => {
    const wrapper = mount(MacroPage); await flushPromises();
    expect(wrapper.text()).toContain('Risk On'); expect(wrapper.text()).toContain('72 / 100');
    for (const label of ['利率环境宽松', '信用健康', '美元偏强', '波动平稳', '数据日期：2026-09-11', 'Signal Coverage 85%']) expect(wrapper.text()).toContain(label);
    const alert = wrapper.get('[data-testid="macro-quality"]');
    expect(alert.text()).toContain('11 / 13'); for (const symbol of ['UUP.US', 'VIX.US', 'TLT.US']) expect(alert.text()).toContain(symbol);
    const table = wrapper.get('[data-testid="macro-instrument-table"]');
    for (const label of ['TLT', '利率', '80.87', '+0.11%', '-1.46%', '↓ Down', '—']) expect(table.text()).toContain(label);
    expect(table.find('.text-market-up').text()).toBe('+0.11%');
    expect(wrapper.get('[data-testid="macro-ratio-table"]').text()).toContain('数据不足');
    expect(wrapper.get('[data-testid="macro-ratio-table"]').text()).toContain('0.754');
  });
  it('preserves null score and regime and keeps complete quality compact', async () => {
    vi.mocked(getMacroDashboard).mockResolvedValue({ ...dashboard(), riskScore: null, regime: null, dataQuality: { ...quality, partial: false } });
    const wrapper = mount(MacroPage); await flushPromises();
    const card = wrapper.get('[data-testid="macro-risk-score"]');
    expect(card.text()).toContain('数据不足'); expect(card.text()).not.toContain('/ 100'); expect(card.find('[role="progressbar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="macro-quality"]').exists()).toBe(false);
  });
  it('opens contribution drawer with N/A rather than zero', async () => {
    const wrapper = mount(MacroPage, { attachTo: document.body }); await flushPromises();
    await wrapper.get('[data-testid="macro-signal-details"]').trigger('click'); await flushPromises();
    expect(document.body.textContent).toContain('N/A / 20'); expect(document.body.textContent).toContain('数据不足 / 过期');
  });
  it('isolates chart failures from dashboard and retries', async () => {
    vi.mocked(getMacroSeries).mockRejectedValueOnce(new Error('offline'));
    const wrapper = mount(MacroPage); await flushPromises();
    expect(wrapper.text()).toContain('跨资产走势图加载失败'); expect(wrapper.text()).toContain('Risk On');
    const chart = wrapper.get('[data-testid="macro-performance-chart"]');
    await chart.findAll('button').find(b => b.text() === '重新加载')!.trigger('click'); await flushPromises();
    expect(chart.text()).not.toContain('跨资产走势图加载失败');
  });
  it('retries dashboard failures independently', async () => {
    vi.mocked(getMacroDashboard).mockRejectedValueOnce(new Error('offline'));
    const wrapper = mount(MacroPage); await flushPromises();
    expect(wrapper.text()).toContain('宏观数据加载失败'); expect(wrapper.findAllComponents(MacroSeriesChart)).toHaveLength(2);
    await wrapper.findAll('button').find(b => b.text() === '重新加载')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('Risk On');
  });
});
describe('Macro series requests', () => {
  it('requests six core assets and the four normalized ratios independently', async () => {
    mount(MacroPage); await flushPromises();
    expect(getMacroSeries).toHaveBeenCalledWith({ range: '60d', mode: 'normalized', symbols: defaultAssets });
    expect(getMacroSeries).toHaveBeenCalledWith({ range: '60d', mode: 'normalized', series: ratioKeys });
  });
  it('supports all ranges, modes, asset selection and an eight-asset limit', async () => {
    const wrapper = mount(MacroPerformanceChart); await flushPromises();
    for (const range of ['20d', '120d', '250d', 'ytd', '60d']) { await wrapper.get('select[data-testid="macro-range"]').setValue(range); await flushPromises(); expect(getMacroSeries).toHaveBeenLastCalledWith(expect.objectContaining({ range })); }
    await wrapper.get('select[data-testid="macro-mode"]').setValue('relative'); await flushPromises();
    expect(getMacroSeries).toHaveBeenLastCalledWith(expect.objectContaining({ mode: 'relative', benchmark: 'SPY.US' }));
    await wrapper.get('select[data-testid="macro-mode"]').setValue('price'); await flushPromises();
    expect(getMacroSeries).toHaveBeenLastCalledWith({ range: '60d', mode: 'price', symbols: defaultAssets });
    for (const code of ['VIX.US', 'GLD.US']) await wrapper.get(`[data-testid="macro-asset-${code}"]`).trigger('click'); await flushPromises();
    expect(getMacroSeries).toHaveBeenLastCalledWith(expect.objectContaining({ symbols: [...defaultAssets, 'VIX.US', 'GLD.US'] }));
    expect(wrapper.get('[data-testid="macro-asset-SMH.US"]').attributes('disabled')).toBeDefined();
    for (const code of [...defaultAssets, 'VIX.US', 'GLD.US']) await wrapper.get(`[data-testid="macro-asset-${code}"]`).trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('暂无走势数据');
    expect(vi.mocked(getMacroSeries).mock.calls.every(([params]) => params!.symbols!.length > 0)).toBe(true);
  });
  it('ignores stale success and error responses and retains chart during loading', async () => {
    const wrapper = mount(MacroPerformanceChart); await flushPromises();
    let resolveOld!: (value: MacroSeriesResult) => void;
    vi.mocked(getMacroSeries).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    await wrapper.get('select').setValue('250d');
    expect(wrapper.text()).toContain('加载中'); expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(true);
    vi.mocked(getMacroSeries).mockResolvedValueOnce(series(120));
    await wrapper.get('select').setValue('20d'); await flushPromises();
    resolveOld(series(80)); await flushPromises();
    expect(wrapper.findComponent(MacroSeriesChart).props('result')!.series[0]!.points[1]!.value).toBe(120);
    let rejectOld!: (reason: Error) => void;
    vi.mocked(getMacroSeries).mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    await wrapper.get('select').setValue('250d'); await wrapper.get('select').setValue('60d'); await flushPromises();
    rejectOld(new Error('stale')); await flushPromises(); expect(wrapper.text()).not.toContain('加载失败');
  });
});
describe('Macro chart rendering', () => {
  it('uses actual dated points, partial legend, normalized tooltip and autoresize', async () => {
    const wrapper = mount(MacroSeriesChart, { props: { result: series(), loading: false, label: '走势' } }); await flushPromises();
    const chart = wrapper.findComponent({ name: 'VChart' }); const option = chart.props('option');
    expect(option.series[0].data).toEqual([['2026-09-08', 100], ['2026-09-11', 105.2]]);
    expect(option.legend.formatter('SPY.US')).toContain('数据不完整');
    expect(option.tooltip.formatter([{ seriesName: 'SPY.US', value: ['2026-09-11', 105.2] }])).toContain('+5.2%');
    expect(chart.props('autoresize')).toBeDefined();
    const ratios = series(); ratios.series[0]!.key = 'HYG_LQD';
    await wrapper.setProps({ result: ratios });
    expect(chart.props('option').tooltip.formatter([{ seriesName: 'HYG_LQD', value: ['2026-09-11', 105.2] }])).toContain('Credit Risk Appetite');
  });
  it('supports light, dark and system theme including chart tokens', async () => {
    const wrapper = mount(MacroSeriesChart, { props: { result: series(), loading: false, label: '走势' } });
    for (const preference of ['dark', 'light', 'system'] as const) {
      document.documentElement.style.setProperty('--foreground', preference === 'light' ? '0 0% 10%' : '0 0% 90%');
      systemPrefersDark.value = true; theme.value = preference; await flushPromises();
      expect(wrapper.findComponent({ name: 'VChart' }).props('option').tooltip.textStyle.color).toContain(preference === 'light' ? '10%' : '90%');
    }
  });
});

it.each([
  [{ rates: 'PRESSURE', credit: 'WEAK', dollar: 'WEAK', volatility: 'ELEVATED' }, ['利率压力', '信用走弱', '美元偏弱', '波动升高']],
  [{ rates: 'NEUTRAL', credit: 'NEUTRAL', dollar: 'NEUTRAL', volatility: 'NEUTRAL' }, ['中性']],
  [{ rates: null, credit: null, dollar: null, volatility: null }, ['数据不足']],
] as const)('renders backend state mappings %j', (states, labels) => {
  const wrapper = mount(MacroStateCards, { props: { dashboard: { ...dashboard(), states: { ...states } } } });
  for (const label of labels) expect(wrapper.text()).toContain(label);
});
