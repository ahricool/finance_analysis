import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useCryptoBtc } from '../useCryptoBtc';

const mocks = vi.hoisted(() => ({ klines: vi.fn(), overview: vi.fn(), signals: vi.fn() }));
vi.mock('@/api/crypto', () => ({
  cryptoApi: mocks, cryptoWebSocketUrl: () => 'ws://localhost/api/v1/crypto/ws',
  parseCryptoMessage: (raw: string) => JSON.parse(raw).market,
}));
class Socket {
  static instances: Socket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor() { Socket.instances.push(this); }
}
const market = { symbol: 'BTCUSDT', enabled: true, ready: true, streamMode: 'websocket', latestCandle: null,
  recentClosed: [], strategyLatestState: null };
const info = { symbol: 'BTCUSDT', market, strategy: null, state: { positionState: 'FLAT' } };
const candle = { symbol: 'BTCUSDT', openTime: '2026-09-01T00:00:00Z', closeTime: '2026-09-01T00:01:00Z',
  open: '100', high: '102', low: '99', close: '101', volume: '1', closed: true };

describe('BTC realtime fallback', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    mocks.klines.mockResolvedValue({ items: [candle] });
    mocks.overview.mockResolvedValue(info);
    mocks.signals.mockResolvedValue({ items: [] });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
  function setup() {
    let state!: ReturnType<typeof useCryptoBtc>;
    const wrapper = mount(defineComponent({ setup() { state = useCryptoBtc(); return () => null; } }));
    return { wrapper, get state() { return state; } };
  }

  it('falls back every 60 seconds, recovers on valid WS data, and stops polling/cleans up', async () => {
    const { wrapper, state } = setup();
    await flushPromises();
    expect(mocks.klines).toHaveBeenCalledWith(1000);
    Socket.instances[0]!.onerror?.();
    await flushPromises();
    expect(state.connection.value).toBe('http_fallback');
    expect(mocks.klines).toHaveBeenLastCalledWith(5);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(mocks.klines.mock.calls.filter(([limit]) => limit === 5).length).toBe(2);
    await vi.advanceTimersByTimeAsync(15_000); // next recovery attempt after the silent socket timed out
    Socket.instances.at(-1)!.onmessage?.({ data: JSON.stringify({ market }) });
    await flushPromises();
    expect(state.connection.value).toBe('websocket');
    expect(mocks.klines).toHaveBeenLastCalledWith(1000);
    const count = mocks.klines.mock.calls.length;
    // Heartbeats keep WS healthy across more than one fallback interval.
    for (let index = 0; index < 7; index++) {
      await vi.advanceTimersByTimeAsync(10_000);
      Socket.instances.at(-1)!.onmessage?.({ data: JSON.stringify({ market }) });
    }
    expect(mocks.klines).toHaveBeenCalledTimes(count);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(mocks.klines).toHaveBeenCalledTimes(count);
    expect(Socket.instances.at(-1)!.close).toHaveBeenCalled();
  });

  it('updates current candle without replacing closed history and reconciles closed minutes idempotently', async () => {
    const { wrapper, state } = setup();
    await flushPromises();
    const previous = state.candles.value;
    const next = { ...candle, openTime: '2026-09-01T00:01:00Z', closed: false };
    Socket.instances[0]!.onmessage?.({ data: JSON.stringify({ market: { ...market, latestCandle: next } }) });
    await flushPromises();
    expect(state.current.value?.openTime).toBe(next.openTime);
    expect(state.candles.value).toBe(previous);
    const final = { ...next, closed: true };
    const frame = { market: { ...market, recentClosed: [candle, final], latestCandle: final } };
    Socket.instances[0]!.onmessage?.({ data: JSON.stringify(frame) });
    Socket.instances[0]!.onmessage?.({ data: JSON.stringify(frame) });
    expect(state.candles.value).toHaveLength(2);
    wrapper.unmount();
  });

  it('times out a silent connection and never polls after authentication rejection', async () => {
    const { wrapper, state } = setup();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(state.connection.value).toBe('http_fallback');
    await vi.advanceTimersByTimeAsync(15_000);
    Socket.instances.at(-1)!.onclose?.({ code: 4401 });
    const count = mocks.klines.mock.calls.length;
    expect(state.connection.value).toBe('unauthorized');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(mocks.klines).toHaveBeenCalledTimes(count);
    wrapper.unmount();
  });
});
