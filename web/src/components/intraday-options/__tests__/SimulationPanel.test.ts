import { mount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import SimulationPanel from '../SimulationPanel.vue';
import type { IntradayOptionsSnapshot } from '@/api/intradayOptions';

afterEach(() => vi.useRealTimers());
it('labels simulated positions, keeps event identity on replay and masks stale execution', async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-17T16:00:00Z'));
  const state = { symbol: 'SPY.US', calculatedAt: '2026-11-17T16:00:00Z', cutoff: '2026-11-17T19:00:00Z',
    quoteTime: '2026-11-17T15:59:58Z', currentPrice: 101, plans: [{ structureId: 'one', kind: 'box_breakout',
      direction: 'bullish', executionReason: '可以模拟进场', targetSource: '未知', confirmedAt: '2026-11-17T15:59:00Z' }] };
  const snapshot = { items: [{ symbol: 'SPY.US', simulation: state }], simulation: { states: [{ symbol: 'SPY.US',
    position: { side: 1, entryPrice: 100, entryAt: '2026-11-17T15:55:00Z', returnPct: 1, invalidation: 99,
      protection: 99.5, target: null, lastPriceAt: '2026-11-17T15:59:58Z' } }], trades: [], statistics: [],
    events: [{ id: 7, symbol: 'SPY.US', at: '2026-11-17T15:55:00Z', reason: '模拟做多进场' }] } } as unknown as IntradayOptionsSnapshot;
  const wrapper = mount(SimulationPanel, { props: { snapshot, disconnected: false }, global: { stubs: { FieldSelect: true } } });
  expect(wrapper.text()).toContain('模拟持有多');
  expect(wrapper.text()).toContain('不是期权收益');
  expect(wrapper.text()).toContain('可以模拟进场');
  await wrapper.setProps({ snapshot: structuredClone(snapshot) });
  expect(wrapper.findAll('li')).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(16000);
  expect(wrapper.text()).toContain('当前入场资格未知');
  expect(wrapper.text()).not.toContain('可以模拟进场');
  wrapper.unmount();
});
