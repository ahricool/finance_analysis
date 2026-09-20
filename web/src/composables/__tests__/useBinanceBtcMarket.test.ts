import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useBinanceBtcMarket } from '../useBinanceBtcMarket';
import { BINANCE_INTERVALS } from '@/types/binance';

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; this.onclose?.(); });
  constructor(public url: string) { Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  message(data: object) { this.onmessage?.({ data: JSON.stringify(data) }); }
}
const start = Date.UTC(2026, 8, 1);
const row = (price = '100') => [start, '100', '110', '90', price, '2', start + 59_999, '200', 2, '1', '100'];
const response = (price = '100') => ({ ok: true, json: async () => [row(price)] });
const fetcher = vi.fn();
let wrapper: ReturnType<typeof mount>;
function setup() {
  let state!: ReturnType<typeof useBinanceBtcMarket>;
  wrapper = mount(defineComponent({ setup() { state = useBinanceBtcMarket(); return () => null; } }));
  return state;
}
function kline(interval = '1m', closed = false, price = '105') {
  return { e: 'kline', s: 'BTCUSDT', k: { i: interval, t: start + 60_000, T: start + 119_999,
    o: '100', h: '110', l: '90', c: price, v: '2', q: '200', n: 2, V: '1', Q: '100', x: closed } };
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(start + 90_000);
  Socket.instances = []; fetcher.mockReset().mockResolvedValue(response());
  vi.stubGlobal('WebSocket', Socket); vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('direct Binance BTC market', () => {
  it('uses one socket for price and all eight periods, with native REST intervals', async () => {
    const state = setup(); const socket = Socket.instances[0]!;
    socket.open(); await flushPromises();
    expect(socket.url).toBe('wss://data-stream.binance.vision/ws');
    expect(socket.send.mock.calls.map(([raw]) => JSON.parse(raw).params)).toContainEqual(['btcusdt@aggTrade']);
    socket.message({ e: 'aggTrade', s: 'BTCUSDT', p: '108' });
    expect(state.price.value).toBe('108');
    for (const interval of BINANCE_INTERVALS.slice(1)) {
      const old = state.interval.value;
      state.interval.value = interval;
      await flushPromises();
      expect(fetcher.mock.lastCall?.[0]).toContain(`interval=${interval}`);
      const commands = socket.send.mock.calls.map(([raw]) => JSON.parse(raw));
      expect(commands).toContainEqual(expect.objectContaining({ method: 'UNSUBSCRIBE', params: [`btcusdt@kline_${old}`] }));
      expect(commands.at(-1).params).toEqual([`btcusdt@kline_${interval}`]);
      socket.message(kline(old));
      expect(state.current.value).toBeNull();
    }
    expect(Socket.instances).toHaveLength(1);
    expect(fetcher.mock.calls.every(([url]) => url.startsWith('https://data-api.binance.vision/'))).toBe(true);
  });

  it('updates and closes the latest candle and reconnects with only the current subscription', async () => {
    const state = setup(); const first = Socket.instances[0]!; first.open(); await flushPromises();
    first.message(kline()); expect(state.current.value?.close).toBe('105');
    first.message(kline('1m', true, '106'));
    expect(state.candles.value.at(-1)?.close).toBe('106'); expect(state.current.value).toBeNull();
    first.message(kline('1m', false)); expect(state.current.value).toBeNull();
    first.close(); expect(state.connection.value).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(3000);
    const second = Socket.instances[1]!; second.open(); await flushPromises();
    expect(state.connection.value).toBe('live');
    expect(second.send.mock.calls.map(([raw]) => JSON.parse(raw).params)).toEqual([['btcusdt@aggTrade'], ['btcusdt@kline_1m']]);
    wrapper.unmount(); expect(second.close).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(60_000); expect(Socket.instances).toHaveLength(2);
  });

  it('ignores late REST responses after interval changes and preserves events newer than REST', async () => {
    let resolveFirst!: (value: ReturnType<typeof response>) => void;
    fetcher.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }));
    const state = setup(); const socket = Socket.instances[0]!; socket.open();
    state.interval.value = '5m'; await flushPromises();
    resolveFirst(response('99')); await flushPromises();
    expect(state.candles.value[0]?.interval).toBe('5m');
    let resolveNext!: (value: ReturnType<typeof response>) => void;
    fetcher.mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve; }));
    const pending = state.refresh();
    socket.message(kline('5m', true, '109'));
    resolveNext(response()); await pending;
    expect(state.candles.value.at(-1)?.close).toBe('109');
  });

  it('allows REST retry independently of WS price and never polls a backend fallback', async () => {
    fetcher.mockRejectedValueOnce(new Error('offline'));
    const state = setup(); const socket = Socket.instances[0]!; socket.open(); await flushPromises();
    expect(state.restError.value).toContain('重试');
    socket.message({ e: 'aggTrade', s: 'BTCUSDT', p: '107' });
    expect(state.price.value).toBe('107');
    await state.refresh(); expect(state.restError.value).toBeNull();
    const count = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000); expect(fetcher).toHaveBeenCalledTimes(count);
  });
});
