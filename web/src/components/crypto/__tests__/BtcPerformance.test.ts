import { mount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import BtcPerformance from '../BtcPerformance.vue';
import type { CryptoPerformance } from '@/types/crypto';
export const performance: CryptoPerformance = {
  performanceStartAt: '2026-09-01T00:00:00Z', performanceEndAt: '2026-09-01T00:15:00Z',
  currentPosition: { positionPct: '0.5', averageEntryPrice: '100' }, executionCount: 3, completedCycles: 2,
  winCount: 1, lossCount: 1, winRate: '0.5', averageReturn: '0.02', cumulativeReturn: '0.04', maxDrawdown: '0.2',
  bestTrade: '0.1', worstTrade: '-0.06', recentExecutions: [], recentTrades: [],
  equityCurve: [{ evaluatedAt: '2026-09-01T00:00:00Z', equity: '1', drawdown: '0' }],
};
it('shows derived performance and recalculates floating contribution from Binance price alone', async () => {
  const wrapper = mount(BtcPerformance, { props: { performance, price: '110' } });
  expect(wrapper.text()).toContain('10.00%'); expect(wrapper.text()).toContain('5.00%');
  expect(wrapper.text()).toContain('20.00%'); expect(wrapper.text()).toContain('50.00%');
  expect(wrapper.text()).toContain('净值曲线等待更多');
  await wrapper.setProps({ performance: { ...performance, equityCurve: [...performance.equityCurve, { evaluatedAt: '2026-09-01T00:15:00Z', equity: '1.04', drawdown: '0' }] } });
  expect(wrapper.find('svg').exists()).toBe(true);
  await wrapper.setProps({ price: '120' }); expect(wrapper.text()).toContain('10.00%');
  await wrapper.setProps({ performance: { ...performance, currentPosition: { positionPct: '0', averageEntryPrice: null } } });
  expect(wrapper.text()).toContain('—');
  wrapper.unmount();
});
