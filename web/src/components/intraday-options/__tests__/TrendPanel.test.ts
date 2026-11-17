import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import TrendPanel from '../TrendPanel.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { fetchIntradayMarket } from '@/api/intradayMarket';
import type { IntradaySnapshot } from '@/api/intradayMarket';
import type { SimTrade, SimulationSnapshot } from '@/api/intradayOptions';
vi.mock('@/api/intradayMarket', () => ({ fetchIntradayMarket: vi.fn() }));
vi.mock('klinecharts', () => ({ registerOverlay: vi.fn() }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
it('passes persisted B/S overlays to minute detail, selects evidence, updates exit on live replay and clears on symbol change', async () => {
  vi.useFakeTimers();
  const at = '2026-11-17T17:00:00Z';
  const t = { id: 'spy1', symbol: 'SPY.US', side: -1, kind: 'box_breakout', entryAt: at, entryPriceAt: at, entryPrice: 100 } as SimTrade;
  const simulation: SimulationSnapshot = { states: [{ symbol: 'SPY.US', position: t } as SimulationSnapshot['states'][number]], trades: [], events: [], statistics: [] };
  vi.mocked(fetchIntradayMarket).mockResolvedValue({ tradingDate: '2026-11-17', reset: true, items: [
    { timestamp: Date.parse(at), open: 100, high: 101, low: 99, close: 100, volume: 10, turnover: null, confirmed: true, sampled: false, partial: false },
    { timestamp: Date.parse(at) + 60000, open: 100, high: 101, low: 99, close: 100, volume: 10, turnover: null, confirmed: false, sampled: false, partial: false },
  ] } as IntradaySnapshot);
  const wrapper = mount(TrendPanel, { props: { symbol: 'SPY.US', result: null, stale: false, simulation },
    global: { stubs: { MarketKLineChart: true, OpportunityPanel: true, FieldSelect: true } } });
  await flushPromises();
  const chart = wrapper.getComponent(MarketKLineChart);
  const overlays = () => chart.props('overlays')!.filter(o => o.groupId === 'intraday-simulation-trades');
  expect(overlays()).toHaveLength(1);
  overlays()[0]!.onClick!({} as never); await wrapper.vm.$nextTick();
  expect(wrapper.get('[data-testid="simulation-trade-detail"]').text()).toContain('S · 模拟做空进场');
  expect(chart.props('focusTimestamp')).toBe(Date.parse(at));
  const closed = { ...t, exitAt: '2026-11-17T17:01:05Z', exitPrice: 99.5, exitPriceAt: '2026-11-17T17:01:04Z', exitReason: '到达目标' };
  await wrapper.setProps({ simulation: { ...simulation, states: [], trades: [closed, closed] } });
  expect(overlays()).toHaveLength(2);
  overlays()[1]!.onClick!({} as never); await wrapper.vm.$nextTick();
  expect(wrapper.get('[data-testid="simulation-trade-detail"]').text()).toContain('B · 模拟做空退场');
  expect(wrapper.text()).toContain('到达目标');
  await wrapper.findAll('button').find(b => b.text().includes('模拟 B/S'))!.trigger('click');
  expect(overlays()).toHaveLength(0);
  await wrapper.setProps({ symbol: 'QQQ.US' }); await flushPromises();
  expect(wrapper.find('[data-testid="simulation-trade-detail"]').exists()).toBe(false);
  expect(overlays()).toHaveLength(0);
  wrapper.unmount();
});
