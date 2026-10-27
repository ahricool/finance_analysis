import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import StockDetailDialog from '../StockDetailDialog.vue';
import { stocksApi } from '@/api/stocks';
import type { StockDetailTab } from '../detail/types';
vi.mock('../detail/HoldingsDetailPanel.vue', () => ({ __esModule: true, default: { name: 'HoldingsDetailPanel', props: ['symbol', 'market', 'context'], emits: ['updated'], template: '<div data-testid="holding-panel">{{ symbol }}<button @click="$emit(\'updated\')">updated</button></div>' } }));
vi.mock('../detail/TrendDetailPanel.vue', () => ({ __esModule: true, default: { name: 'TrendDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="trend-panel">{{ symbol }}</div>' } }));
vi.mock('../detail/ETFDetailPanel.vue', () => ({ __esModule: true, default: { name: 'ETFDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="etf-panel">{{ symbol }}</div>' } }));
vi.mock('../detail/ConfluenceDetailPanel.vue', () => ({ __esModule: true, default: { name: 'ConfluenceDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="confluence-panel">{{ symbol }}</div>' } }));
vi.mock('../detail/IntradayDetailPanel.vue', () => ({ __esModule: true, default: { name: 'IntradayDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="intraday-panel">{{ symbol }}</div>' } }));
vi.mock('../detail/DragonTigerDetailPanel.vue', () => ({ __esModule: true, default: { name: 'DragonTigerDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="dragon-panel">{{ symbol }}</div>' } }));
vi.mock('../detail/QuantDetailPanel.vue', () => ({ __esModule: true, default: { name: 'QuantDetailPanel', props: ['symbol', 'market', 'context'], template: '<div data-testid="quant-panel">{{ symbol }}</div>' } }));
vi.mock('@/api/stocks', () => ({ stocksApi: { quote: vi.fn(), classification: vi.fn().mockResolvedValue({ memberships: { industries: [] } }) } }));
beforeEach(() => { vi.mocked(stocksApi.quote).mockReset().mockResolvedValue({ code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: false }); });
const stock = { code: 'AAPL.US', name: 'Apple', marketType: 'US' as const };
const slots = { template: '<div><slot /></div>' };
const stubs = { Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' }, DialogContent: slots, DialogHeader: slots, DialogTitle: slots, DialogDescription: slots, ResearchEvidence: true, DailyKLineCard: true, OptionsPanel: { name: 'OptionsPanel', props: ['symbol', 'initialView', 'initialDate'], template: '<div />' } };
function render(initialTab: StockDetailTab = 'overview') {
  return mount(StockDetailDialog, { props: { stock, kind: 'research', initialTab, context: { tradeDate: '2026-10-09', view: 'official' } }, global: { stubs } });
}
async function tab(wrapper: ReturnType<typeof render>, label: string) {
  const button = wrapper.findAll('[role="tab"]').find(item => item.text() === label)!;
  await button.trigger('mousedown', { button: 0, ctrlKey: false }); await flushPromises();
}
describe('unified StockDetailDialog', () => {
  it('preserves legacy stock-driven opening and presents accessible responsive tabs', () => {
    const wrapper = render();
    expect(wrapper.text()).toContain('Apple');
    expect(wrapper.findAll('[role="tab"]').map(item => item.text())).toEqual(['行情', '持仓', '期权', '趋势', 'ETF 轮动', '共振', '盘中确认', '量化', '研究概览']);
    expect(wrapper.get('[role="tabpanel"]').attributes('aria-labelledby')).toBe(wrapper.get('[role="tab"][data-state="active"]').attributes('id'));
    expect(wrapper.get('[data-testid="stock-detail-tabs"]').element.parentElement?.classList.contains('overflow-x-auto')).toBe(true);
    wrapper.unmount();
  });
  it('switches between every supported research panel without changing the stock', async () => {
    const wrapper = render();
    for (const [label, testid] of [['持仓', 'holding'], ['趋势', 'trend'], ['ETF 轮动', 'etf'], ['共振', 'confluence'], ['盘中确认', 'intraday'], ['量化', 'quant']]) {
      await tab(wrapper, label!);
      expect(wrapper.get(`[data-testid="${testid}-panel"]`).text()).toContain(stock.code);
      expect(wrapper.get('[role="tabpanel"]').findAll('[data-testid$="-panel"]')).toHaveLength(1);
    }
    wrapper.unmount();
  });
  it('passes source date/view into options and preserves its explicit legacy props', async () => {
    const wrapper = render('trend'); await flushPromises();
    await tab(wrapper, '期权');
    expect(wrapper.findComponent({ name: 'OptionsPanel' }).props()).toMatchObject({ symbol: stock.code, initialView: 'official', initialDate: '2026-10-09' });
    await wrapper.setProps({ initialTab: 'options', optionsView: 'preview', optionsDate: '2026-10-12' }); await flushPromises();
    expect(wrapper.findComponent({ name: 'OptionsPanel' }).props()).toMatchObject({ initialView: 'preview', initialDate: '2026-10-12' });
    wrapper.unmount();
  });
  it('normalizes legacy options date/view for every other tab', async () => {
    const wrapper = render('options');
    await wrapper.setProps({ context: undefined, optionsView: 'preview', optionsDate: '2026-10-12' });
    await tab(wrapper, '趋势');
    expect(wrapper.findComponent({ name: 'TrendDetailPanel' }).props('context')).toEqual({ view: 'preview', tradeDate: '2026-10-12' });
    await tab(wrapper, '量化');
    expect(wrapper.findComponent({ name: 'QuantDetailPanel' }).props('context')).toEqual({ view: 'preview', tradeDate: '2026-10-12' });
    wrapper.unmount();
  });
  it('replaces panel identity and date atomically when another stock or context is selected', async () => {
    const wrapper = render('trend'); await flushPromises();
    const first = wrapper.findComponent({ name: 'TrendDetailPanel' }).vm;
    await wrapper.setProps({ stock: { ...stock, code: 'MSFT.US', name: 'Microsoft' }, context: { tradeDate: '2026-10-08', view: 'official' } }); await flushPromises();
    const current = wrapper.findComponent({ name: 'TrendDetailPanel' });
    expect(current.vm).not.toBe(first);
    expect(current.props()).toMatchObject({ symbol: 'MSFT.US', context: { tradeDate: '2026-10-08' } });
    expect(wrapper.text()).not.toContain('Apple'); wrapper.unmount();
  });
  it('unmounts closed content and reopens the source tab for the same identity', async () => {
    const wrapper = render('holdings'); await flushPromises();
    await tab(wrapper, '趋势');
    await wrapper.setProps({ open: false }); await flushPromises();
    expect(wrapper.find('[role="tabpanel"]').exists()).toBe(false);
    await wrapper.setProps({ open: true }); await flushPromises();
    expect(wrapper.find('[data-testid="holding-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="trend-panel"]').exists()).toBe(false); wrapper.unmount();
  });
  it('does not keep unsupported US tabs when switching markets', async () => {
    const wrapper = render('options'); await flushPromises();
    await wrapper.setProps({ stock: { code: '600519.SH', name: '贵州茅台', marketType: 'CN' } }); await flushPromises();
    expect(wrapper.findComponent({ name: 'OptionsPanel' }).exists()).toBe(false);
    expect(wrapper.findAll('[role="tab"]').map(item => item.text())).toContain('龙虎榜');
    await tab(wrapper, '龙虎榜'); expect(wrapper.get('[data-testid="dragon-panel"]').text()).toBe('600519.SH');
    await wrapper.setProps({ stock: { code: '00700.HK', name: '腾讯控股', marketType: 'HK' } }); await flushPromises();
    expect(wrapper.findAll('[role="tab"]').map(item => item.text())).toEqual(['行情', '持仓']);
    wrapper.unmount();
  });
  it('forwards holding updates without closing the modal', async () => {
    const wrapper = render('holdings'); await flushPromises();
    await wrapper.get('[data-testid="holding-panel"] button').trigger('click');
    expect(wrapper.emitted('holdings-updated')).toHaveLength(1);
    expect(wrapper.find('[role="tabpanel"]').exists()).toBe(true); wrapper.unmount();
  });
  it('loads a quote only when overview is active and prefers a matching supplied quote', async () => {
    const wrapper = render('trend'); await flushPromises();
    expect(stocksApi.quote).not.toHaveBeenCalled();
    await tab(wrapper, '行情');
    expect(stocksApi.quote).toHaveBeenCalledWith('AAPL.US', 'US', expect.any(AbortSignal));
    await wrapper.setProps({ quote: { code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 222 } });
    expect(wrapper.text()).toContain('222');
    await tab(wrapper, '持仓'); await tab(wrapper, '行情');
    expect(stocksApi.quote).toHaveBeenCalledTimes(1); wrapper.unmount();
  });
  it('ignores a quote prop for another identity and aborts stale fetches on navigation and close', async () => {
    let finish!: (data: Awaited<ReturnType<typeof stocksApi.quote>>) => void;
    vi.mocked(stocksApi.quote).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = render();
    const firstSignal = vi.mocked(stocksApi.quote).mock.calls[0]![2]!;
    vi.mocked(stocksApi.quote).mockResolvedValue({ code: 'MSFT.US', symbol: 'MSFT.US', marketType: 'US', available: true, lastPrice: 333 });
    await wrapper.setProps({ stock: { ...stock, code: 'MSFT.US', name: 'Microsoft' }, quote: { code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 111 } }); await flushPromises();
    expect(firstSignal.aborted).toBe(true);
    finish({ code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 111 }); await flushPromises();
    expect(wrapper.text()).toContain('333'); expect(wrapper.text()).not.toContain('111');
    const currentSignal = vi.mocked(stocksApi.quote).mock.calls.at(-1)![2]!;
    await wrapper.setProps({ open: false });
    expect(currentSignal.aborted).toBe(true); wrapper.unmount();
  });
  it('distinguishes missing quote data from a failed request and supports retry', async () => {
    vi.mocked(stocksApi.quote).mockRejectedValueOnce({ response: { status: 404 } });
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain('暂无该股票的实时行情');
    vi.mocked(stocksApi.quote).mockRejectedValueOnce(new Error('quote unavailable'));
    await wrapper.findAll('button').find(button => button.text() === '刷新行情')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('重试行情');
    expect(wrapper.text()).not.toContain('暂无该股票的实时行情');
    vi.mocked(stocksApi.quote).mockResolvedValueOnce({ code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 444 });
    await wrapper.findAll('button').find(button => button.text() === '重试行情')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('444'); wrapper.unmount();
  });

  it('does not reset the active tab when an unchanged source record is recreated', async () => {
    const wrapper = render('holdings'); await flushPromises();
    await tab(wrapper, '趋势');
    const panel = wrapper.findComponent({ name: 'TrendDetailPanel' }).vm;
    await wrapper.setProps({ stock: { ...stock }, context: { tradeDate: '2026-10-09', view: 'official' } }); await flushPromises();
    expect(wrapper.findComponent({ name: 'TrendDetailPanel' }).vm).toBe(panel);
    wrapper.unmount();
  });

  it('retains merged watch-scoped hints in the shared overview', async () => {
    const wrapper = render();
    await wrapper.setProps({ kind: 'holding', stock: { ...stock, quantity: '10', avgCost: '100' }, quote: { code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 222 } });
    await flushPromises();
    const hints = wrapper.findAllComponents({ name: 'IndicatorHelpLabel' });
    for (const label of ['最新价', '成交量 (Volume)', '平均成本', '持仓收益率']) {
      expect(hints.find(hint => hint.props('label') === label)?.props('scope')).toBe('watch');
    }
    wrapper.unmount();
  });

});

it('keeps general charts and price action in the first market tab and loads research summaries separately', async () => {
  const wrapper = render('trend'); await flushPromises();
  expect(wrapper.findComponent({ name: 'DailyKLineCard' }).exists()).toBe(false);
  expect(wrapper.findComponent({ name: 'ResearchEvidence' }).exists()).toBe(false);
  await tab(wrapper, '行情');
  const chart = wrapper.findComponent({ name: 'DailyKLineCard' });
  expect(chart.attributes('symbol')).toBe('AAPL.US');
  expect(chart.attributes('highlight-date')).toBe('2026-10-09');
  expect(wrapper.findComponent({ name: 'ResearchEvidence' }).exists()).toBe(false);
  await tab(wrapper, '研究概览');
  expect(wrapper.findComponent({ name: 'DailyKLineCard' }).exists()).toBe(false);
  expect(wrapper.findComponent({ name: 'ResearchEvidence' }).exists()).toBe(true);
  wrapper.unmount();
});
