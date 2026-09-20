/* eslint-disable vue/one-component-per-file -- Independent lifecycle harnesses for composable tests. */
import { defineComponent, ref } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import { useCryptoStrategy } from '../useCryptoStrategy';
const api = vi.hoisted(() => ({ overview: vi.fn(), signals: vi.fn(), performance: vi.fn(), strategies: vi.fn().mockResolvedValue([]), summaries: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/crypto', () => ({ cryptoApi: api }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
it('refreshes strategy independently and stops after unmount', async () => {
  vi.useFakeTimers();
  api.overview.mockResolvedValue({ symbol: 'BTCUSDT', strategy: null, state: { positionState: 'FLAT' } });
  api.signals.mockResolvedValue({ items: [] });
  api.performance.mockResolvedValue({ performanceStartAt: null });
  let state!: ReturnType<typeof useCryptoStrategy>;
  const wrapper = mount(defineComponent({ setup() { state = useCryptoStrategy(); return () => null; } }));
  await flushPromises();
  expect(state.overview.value?.state.positionState).toBe('FLAT');
  await vi.advanceTimersByTimeAsync(60_000); expect(api.overview).toHaveBeenCalledTimes(2);
  api.overview.mockRejectedValueOnce(new Error('offline'));
  await state.refresh(); expect(state.error.value).not.toBeNull();
  await state.refresh(); expect(state.error.value).toBeNull();
  wrapper.unmount();
  await vi.advanceTimersByTimeAsync(60_000); expect(api.overview).toHaveBeenCalledTimes(4);
});

it('does not apply a late signal response from an old chart window', async () => {
  vi.useFakeTimers();
  const range = ref({ start: '2026-09-01T00:00:00Z', end: '2026-09-02T00:00:00Z' });
  let resolveOld!: (value: object) => void;
  api.signals.mockImplementation((_key: string, arg?: object) => arg && arg === range.value
    ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve({ items: [] }));
  let state!: ReturnType<typeof useCryptoStrategy>;
  const wrapper = mount(defineComponent({ setup() { state = useCryptoStrategy(range); return () => null; } }));
  await flushPromises();
  api.signals.mockResolvedValue({ items: [{ action: 'EXIT' }] });
  range.value = { start: '2026-08-01T00:00:00Z', end: '2026-10-01T00:00:00Z' };
  await flushPromises();
  resolveOld({ items: [{ action: 'BUY' }] }); await flushPromises();
  expect(state.markers.value[0]?.action).toBe('EXIT');
  wrapper.unmount();
});

it('switches all strategy data and ignores late responses for the previous key', async () => {
  vi.useFakeTimers();
  let resolveOld!: (value: object) => void;
  api.strategies.mockResolvedValue([
    { strategyKey: 'btc_breakout_v1', enabled: true }, { strategyKey: 'btc_test_v1', enabled: true },
  ]);
  api.summaries.mockResolvedValue([{ strategyKey: 'btc_breakout_v1', totalReturn: '.2' }, { strategyKey: 'btc_test_v1', totalReturn: '-.1' }]);
  api.performance.mockImplementation((key: string) => key === 'btc_breakout_v1'
    ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve({ strategyKey: key, totalReturn: '-.1' }));
  api.overview.mockImplementation((key: string) => Promise.resolve({ strategyKey: key }));
  api.signals.mockImplementation((key: string) => Promise.resolve({ items: [{ strategyKey: key, action: key === 'btc_test_v1' ? 'EXIT' : 'BUY' }] }));
  let state!: ReturnType<typeof useCryptoStrategy>;
  const wrapper = mount(defineComponent({ setup() {
    state = useCryptoStrategy(ref({ start: '2026-09-01T00:00:00Z', end: '2026-09-02T00:00:00Z' })); return () => null;
  } }));
  await flushPromises();
  state.selectedKey.value = 'btc_test_v1'; await flushPromises();
  resolveOld({ strategyKey: 'btc_breakout_v1', totalReturn: '.2' }); await flushPromises();
  expect(state.performance.value?.totalReturn).toBe('-.1');
  expect(state.overview.value?.strategyKey).toBe('btc_test_v1');
  expect(state.signals.value[0]?.strategyKey).toBe('btc_test_v1');
  expect(state.markers.value[0]?.action).toBe('EXIT');
  expect(state.summaries.value.map(value => value.totalReturn)).toEqual(['.2', '-.1']);
  wrapper.unmount();
});
