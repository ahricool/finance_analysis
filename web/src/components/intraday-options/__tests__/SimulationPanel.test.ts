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
    position: { id: 'spy', symbol: 'SPY.US', side: 1, entryPrice: 100, entryAt: '2026-11-17T15:55:00Z', returnPct: 1, invalidation: 99,
      protection: 99.5, target: null, lastPriceAt: '2026-11-17T15:59:58Z' } }], trades: [], statistics: [],
    events: [{ id: 7, kind: 'entry', symbol: 'SPY.US', at: '2026-11-17T15:55:00Z', reason: '模拟做多进场' }] } } as unknown as IntradayOptionsSnapshot;
  const wrapper = mount(SimulationPanel, { props: { snapshot, disconnected: false }, global: { stubs: { FieldSelect: true } } });
  expect(wrapper.text()).toContain('模拟持有多');
  expect(wrapper.text()).toContain('不是期权收益');
  expect(wrapper.text()).toContain('选择单标的');
  await wrapper.findComponent({ name: 'FieldSelect' }).vm.$emit('update:modelValue', 'SPY.US');
  expect(wrapper.text()).toContain('可以模拟进场');
  await wrapper.setProps({ snapshot: structuredClone(snapshot) });
  expect(wrapper.findAll('li')).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(16000);
  expect(wrapper.text()).toContain('当前入场资格未知');
  expect(wrapper.text()).not.toContain('可以模拟进场');
  wrapper.unmount();
});

it('defaults to all positions and important events, deduplicates replay and supports filtering', async () => {
  const snapshot = { items: [{ symbol: 'SPY.US' }, { symbol: 'NVDA.US' }], simulation: {
    states: ['SPY.US', 'NVDA.US'].map((symbol, i) => ({ symbol, position: { id: symbol, symbol,
      side: i ? -1 : 1, entryPrice: 100, entryAt: '2026-11-17T15:00:00Z', lastPriceAt: '2026-11-17T15:59:58Z' } })),
    trades: [], statistics: [], events: [
      { id: 1, symbol: 'SPY.US', kind: 'entry', at: '2026-11-17T15:00:00Z', reason: '模拟进场', trade: { side: 1 } },
      { id: 3, symbol: 'NVDA.US', kind: 'exit', at: '2026-11-17T15:02:00Z', reason: '模拟退场', trade: { side: -1 } },
      { id: 2, symbol: 'SPY.US', kind: 'hold', at: '2026-11-17T15:01:00Z', reason: '保护已启动', side: 1 },
      { id: 4, symbol: 'SPY.US', kind: 'data', at: '2026-11-17T15:03:00Z', reason: '行情延迟' },
    ],
  } } as unknown as IntradayOptionsSnapshot;
  const wrapper = mount(SimulationPanel, { props: { snapshot, disconnected: false }, global: { stubs: { FieldSelect: true } } });
  expect(wrapper.findComponent({ name: 'FieldSelect' }).props('modelValue')).toBe('all');
  expect(wrapper.findAll('[data-testid="simulation-position"]')).toHaveLength(2);
  const section = wrapper.get('[aria-label="最近模拟进退场消息"]');
  expect(section.findAll('li').map(e => e.text())).toEqual([
    expect.stringContaining('NVDA.US · 做空'), expect.stringContaining('保护已启动'), expect.stringContaining('SPY.US · 做多'),
  ]);
  expect(section.find('details').exists()).toBe(false);
  expect(section.text()).not.toContain('行情延迟');
  const replay = structuredClone(snapshot);
  replay.simulation!.events.push(replay.simulation!.events[0]!);
  await wrapper.setProps({ snapshot: replay });
  expect(section.findAll('li')).toHaveLength(3);
  await wrapper.findComponent({ name: 'FieldSelect' }).vm.$emit('update:modelValue', 'NVDA.US');
  expect(wrapper.findAll('[data-testid="simulation-position"]')).toHaveLength(1);
  expect(section.findAll('li')).toHaveLength(1);
  expect(section.text()).toContain('NVDA.US');
  expect(section.text()).not.toContain('SPY.US');
  wrapper.unmount();
});
