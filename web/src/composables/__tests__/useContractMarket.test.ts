import { mount } from '@vue/test-utils';
import { defineComponent, ref, nextTick } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useContractMarket } from '../useContractMarket';

class Socket {
  static instances: Socket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  close = vi.fn();
  constructor(public url: string) { Socket.instances.push(this); }
}

class Events {
  static instances: Events[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) { Events.instances.push(this); }
}

describe('contract live connection', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Socket.instances = [];
    Events.instances = [];
  });
  it('tries WS twice, then sticks to SSE across symbol and interval switches', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', Socket);
    vi.stubGlobal('EventSource', Events);
    const symbol = ref('SOXLUSDT'), interval = ref<'1d' | '1m'>('1d');
    const receive = vi.fn();
    const wrapper = mount(defineComponent({
      setup() { return useContractMarket(symbol, interval, receive); },
      template: '<p>{{ status }}</p>',
    }));
    expect(Socket.instances[0]?.url).toContain('/api/v1/crypto/contracts/ws?symbol=SOXLUSDT&interval=1d&delta=true');
    Socket.instances[0]!.onerror!();
    await vi.advanceTimersByTimeAsync(1500);
    Socket.instances[1]!.onclose!({ code: 1006 });
    await vi.advanceTimersByTimeAsync(1500);
    expect(Events.instances).toHaveLength(1);
    const snap = { items: [], symbol: 'SOXLUSDT', minutes: null, daily_current: null };
    Events.instances[0]!.onmessage!({ data: JSON.stringify(snap) });
    expect(receive).toHaveBeenCalledWith(snap);
    const baseline = { ...snap, items: [{ symbol: 'SOXLUSDT', metrics: null }], revision: 1 };
    Events.instances[0]!.onmessage!({ data: JSON.stringify(baseline) });
    const operation = { op: 'set', path: ['daily_current'], value: { timestamp: 42 } };
    Events.instances[0]!.onmessage!({ data: JSON.stringify({ revision: 2, operations: [operation] }) });
    expect(receive.mock.lastCall?.[0].daily_current).toEqual({ timestamp: 42 });
    for (const [revision, value] of [[3, { buy_share: .65 }], [4, null]]) {
      Events.instances[0]!.onmessage!({ data: JSON.stringify({ revision, operations: [
        { op: 'set', path: ['items', 0, 'metrics'], value },
      ] }) });
      expect(receive.mock.lastCall?.[0].items[0].metrics).toEqual(value);
    }
    await nextTick();
    expect(wrapper.text()).toContain('SSE 已连接');
    const previous = Events.instances[0]!.onmessage!;
    symbol.value = 'ETHUSDT'; interval.value = '1m';
    await nextTick();
    expect(Events.instances[0]!.close).toHaveBeenCalled();
    expect(Events.instances[1]!.url).toContain('/events?symbol=ETHUSDT&interval=1m&delta=true');
    previous({ data: JSON.stringify(snap) });
    expect(receive).toHaveBeenCalledTimes(5);
    wrapper.unmount();
    expect(Events.instances[1]!.close).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('falls back when a socket never receives a payload', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', Socket);
    vi.stubGlobal('EventSource', Events);
    const wrapper = mount(defineComponent({
      setup() { return useContractMarket(ref('ETHUSDT'), ref('1m'), vi.fn()); },
      template: '<p>{{ status }}</p>',
    }));
    await vi.advanceTimersByTimeAsync(27_000);
    expect(Socket.instances).toHaveLength(2);
    expect(Events.instances).toHaveLength(1);
    wrapper.unmount();
  });
});
