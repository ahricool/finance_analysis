import { marketQuoteKey } from '@/api/realtimeMarket';
import * as marketApi from '@/api/realtimeMarket';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
/* eslint-disable vue/one-component-per-file -- Each anonymous component is an isolated composable test host. */
import { mount } from '@vue/test-utils';
import { defineComponent, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  disconnect(code = 1006) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code } as CloseEvent);
  }
}

describe('useRealtimeQuotes', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('indexes quote snapshots, reconnects, and releases the socket on unmount', async () => {
    let state: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({
      setup() {
        state = useRealtimeQuotes();
        return {};
      },
      template: '<div />',
    }));
    const first = MockWebSocket.instances[0];
    expect(first.url).toBe('ws://localhost:3000/api/v1/market-data/ws');
    first.open();
    first.message({
      type: 'quotes',
      generated_at: '2026-06-30T02:30:00Z',
      quotes: [{ code: 'AAPL', market_type: 'US', symbol: 'AAPL.US', available: true, change_pct: 2 }],
    });

    expect(state!.status.value).toBe('connected');
    expect(state!.quotes.value[marketQuoteKey('aapl', 'US')].change_pct).toBe(2);

    first.disconnect();
    expect(state!.status.value).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(1_000);
    expect(MockWebSocket.instances).toHaveLength(2);

    const second = MockWebSocket.instances[1];
    second.open();
    wrapper.unmount();
    expect(second.close).toHaveBeenCalledWith(1000, 'Page closed');
  });

  it('does not reconnect after an authentication close', async () => {
    const wrapper = mount(defineComponent({
      setup() {
        return useRealtimeQuotes();
      },
      template: '<div />',
    }));
    MockWebSocket.instances[0].disconnect(4401);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(MockWebSocket.instances).toHaveLength(1);
    wrapper.unmount();
  });

  it('falls back after exactly two failures, stays on SSE, and aborts on unmount', async () => {
    let signal!: AbortSignal;
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockImplementation(async (_options, nextSignal, accept) => {
      signal = nextSignal;
      accept({ type: 'quotes', generated_at: 'now', quotes: [] });
      await new Promise(() => {});
    });
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({ setup() { state = useRealtimeQuotes(); return {}; }, template: '<div />' }));
    MockWebSocket.instances[0].onerror?.();
    MockWebSocket.instances[0].disconnect(); // Error and close belong to one failed request.
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    expect(sse).toHaveBeenCalledTimes(1);
    expect(state.status.value).toBe('sse');
    await vi.advanceTimersByTimeAsync(10_000);
    expect(MockWebSocket.instances).toHaveLength(2);
    wrapper.unmount();
    expect(signal.aborted).toBe(true);
  });

  it('times out silent sockets and stops all retries on SSE authentication failure', async () => {
    vi.spyOn(marketApi, 'readMarketEvents').mockRejectedValue(new marketApi.MarketStreamAuthError());
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({ setup() { state = useRealtimeQuotes(); return {}; }, template: '<div />' }));
    await vi.advanceTimersByTimeAsync(41_000);
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(state.status.value).toBe('unauthorized');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(marketApi.readMarketEvents).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('retries failed SSE over HTTP without returning to WS', async () => {
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockRejectedValueOnce(new Error('offline'))
      .mockImplementation(() => new Promise(() => {}));
    const wrapper = mount(defineComponent({ setup: () => useRealtimeQuotes(), template: '<div />' }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(sse).toHaveBeenCalledTimes(2);
    expect(MockWebSocket.instances).toHaveLength(2);
    wrapper.unmount();
  });

  it('releases old market streams and ignores their late portfolio snapshots', async () => {
    const market = ref<'CN' | 'US'>('CN');
    const streams: Array<{ signal: AbortSignal; accept: Parameters<typeof marketApi.readMarketEvents>[2] }> = [];
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockImplementation((_options, signal, accept) => {
      streams.push({ signal, accept });
      return new Promise(() => {});
    });
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({
      setup() { state = useRealtimeQuotes(() => ({ scope: 'holdings', market: market.value })); return {}; }, template: '<div />',
    }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    market.value = 'US';
    await nextTick();
    expect(streams[0]!.signal.aborted).toBe(true);
    expect(sse.mock.calls[1]![0]).toEqual({ scope: 'holdings', market: 'US' });
    streams[1]!.accept({ type: 'quotes', generated_at: 'US', quotes: [], portfolio: { market: 'US', positions: [], accounts: [] } });
    streams[0]!.accept({ type: 'quotes', generated_at: 'old CN', quotes: [], portfolio: { market: 'CN', positions: [], accounts: [] } });
    expect(state.portfolio.value?.market).toBe('US');
    expect(state.lastUpdatedAt.value).toBe('US');
    expect(MockWebSocket.instances).toHaveLength(2);
    wrapper.unmount();
  });
});
