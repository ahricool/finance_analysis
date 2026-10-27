import { marketQuoteKey } from '@/api/realtimeMarket';
import * as marketApi from '@/api/realtimeMarket';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
/* eslint-disable vue/one-component-per-file -- Each anonymous component is an isolated composable test host. */
import { mount } from '@vue/test-utils';
import { defineComponent, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { redirectToLogin } from '@/api';

vi.mock('@/api', async importOriginal => ({ ...await importOriginal<typeof import('@/api')>(), redirectToLogin: vi.fn() }));

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

function mockHttpEvents(waitForHeaders = false) {
  const requests: Array<{
    signal: AbortSignal;
    stream: ReadableStreamDefaultController<Uint8Array>;
    respond: () => void;
  }> = [];
  const encoder = new TextEncoder();
  vi.stubGlobal('fetch', vi.fn((_url, options: RequestInit) => new Promise<Response>((resolve, reject) => {
    const signal = options.signal!;
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(controller) { stream = controller; } });
    const respond = () => resolve(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
    requests.push({ signal, stream, respond });
    signal.addEventListener('abort', () => {
      const error = new DOMException('Aborted', 'AbortError');
      stream.error(error);
      reject(error);
    });
    if (!waitForHeaders) respond();
  })));
  return { requests, send(index: number, frame: string) { requests[index]!.stream.enqueue(encoder.encode(frame)); } };
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

  it('does not reconnect after an authentication close and sends the user to login', async () => {
    vi.mocked(redirectToLogin).mockClear();
    const wrapper = mount(defineComponent({
      setup() {
        return useRealtimeQuotes();
      },
      template: '<div />',
    }));
    MockWebSocket.instances[0].disconnect(4401);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(redirectToLogin).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('pauses after a long hidden period and reconnects when visible again', async () => {
    let visibility: DocumentVisibilityState = 'visible';
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    const setVisibility = (value: DocumentVisibilityState) => { visibility = value; document.dispatchEvent(new Event('visibilitychange')); };
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({ setup() { state = useRealtimeQuotes(); return {}; }, template: '<div />' }));
    const socket = MockWebSocket.instances[0];
    socket.open();
    // Keep quotes flowing so the silent-socket watchdog stays out of the picture.
    const tick = async (ms: number) => {
      for (let elapsed = 0; elapsed < ms; elapsed += 10_000) {
        socket.message({ type: 'quotes', generated_at: 'now', quotes: [] });
        await vi.advanceTimersByTimeAsync(10_000);
      }
    };
    setVisibility('hidden');
    await tick(30_000);
    setVisibility('visible');
    await tick(60_000);
    expect(socket.close).not.toHaveBeenCalled();
    setVisibility('hidden');
    await tick(60_000);
    expect(socket.close).toHaveBeenCalled();
    expect(state.status.value).toBe('paused');
    setVisibility('visible');
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(state.status.value).toBe('connecting');
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
    vi.spyOn(marketApi, 'readMarketEvents').mockRejectedValue(new marketApi.MarketStreamAuthError(403));
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
    const streams: Array<{ signal: AbortSignal; accept: Parameters<typeof marketApi.readMarketEvents>[2]; activity: () => void }> = [];
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockImplementation((_options, signal, accept, activity) => {
      streams.push({ signal, accept, activity: activity! });
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
    streams[1]!.activity();
    await vi.advanceTimersByTimeAsync(29_000);
    streams[0]!.activity(); // Stale transport callbacks must not extend the current connection's timeout.
    await vi.advanceTimersByTimeAsync(1_000);
    expect(streams[1]!.signal.aborted).toBe(true);
    wrapper.unmount();
  });

  it.each([false, true])('keeps a live SSE open through slow quotes (first quote received=%s)', async hasQuote => {
    const http = mockHttpEvents();
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const wrapper = mount(defineComponent({ setup() { state = useRealtimeQuotes(); return {}; }, template: '<div />' }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    await vi.advanceTimersByTimeAsync(0);
    if (hasQuote) http.send(0, 'data: {"type":"quotes","generated_at":"first","quotes":[]}\n\n');
    for (let tick = 0; tick < 9; tick++) {
      await vi.advanceTimersByTimeAsync(10_000);
      http.send(0, ': heartbeat\n\n');
      await vi.advanceTimersByTimeAsync(0);
      expect(http.requests[0]!.signal.aborted).toBe(false);
    }
    expect(state.lastUpdatedAt.value).toBe(hasQuote ? 'first' : null);
    expect(state.status.value).toBe('sse');
    expect(http.requests).toHaveLength(1);
    expect(MockWebSocket.instances).toHaveLength(2);
    http.send(0, 'data: {"type":"quotes","generated_at":"slow result","quotes":[]}\n\n');
    await vi.advanceTimersByTimeAsync(0);
    expect(state.lastUpdatedAt.value).toBe('slow result');
    wrapper.unmount();
    expect(http.requests[0]!.signal.aborted).toBe(true);
  });

  it('allows slow HTTP headers, then expires only after transport becomes idle', async () => {
    const http = mockHttpEvents(true);
    const wrapper = mount(defineComponent({ setup: () => useRealtimeQuotes(), template: '<div />' }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    await vi.advanceTimersByTimeAsync(45_000);
    expect(http.requests[0]!.signal.aborted).toBe(false);
    http.requests[0]!.respond();
    await vi.advanceTimersByTimeAsync(29_000);
    // Even an incomplete data frame proves transport activity.
    http.send(0, 'data: {"type":');
    await vi.advanceTimersByTimeAsync(29_999);
    expect(http.requests[0]!.signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(http.requests[0]!.signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(http.requests).toHaveLength(2);
    wrapper.unmount();
  });

  it('times out HTTP requests that never return headers', async () => {
    const http = mockHttpEvents(true);
    const wrapper = mount(defineComponent({ setup: () => useRealtimeQuotes(), template: '<div />' }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    await vi.advanceTimersByTimeAsync(59_999);
    expect(http.requests[0]!.signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(http.requests[0]!.signal.aborted).toBe(true);
    wrapper.unmount();
  });

  it('backs off repeated SSE failures even if headers arrive, and resets after a quote', async () => {
    let accept!: Parameters<typeof marketApi.readMarketEvents>[2];
    let fail!: (error: Error) => void;
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockImplementation((_options, _signal, _onMessage, onActivity) => {
      onActivity?.();
      return Promise.reject(new Error('connection closed'));
    });
    const wrapper = mount(defineComponent({ setup: () => useRealtimeQuotes(), template: '<div />' }));
    MockWebSocket.instances[0].disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1].disconnect();
    await vi.advanceTimersByTimeAsync(0);
    for (const [index, delay] of [5_000, 10_000, 20_000, 30_000, 30_000].entries()) {
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(sse).toHaveBeenCalledTimes(index + 1);
      await vi.advanceTimersByTimeAsync(1);
      expect(sse).toHaveBeenCalledTimes(index + 2);
    }
    sse.mockImplementation((_options, _signal, onMessage, onActivity) => {
      accept = onMessage;
      onActivity?.();
      return new Promise((_resolve, reject) => { fail = reject; });
    });
    await vi.advanceTimersByTimeAsync(30_000);
    accept({ type: 'quotes', generated_at: 'recovered', quotes: [] });
    fail(new Error('lost again'));
    await vi.advanceTimersByTimeAsync(4_999);
    expect(sse).toHaveBeenCalledTimes(7);
    await vi.advanceTimersByTimeAsync(1);
    expect(sse).toHaveBeenCalledTimes(8);
    wrapper.unmount();
  });

  it('rebuilds group sockets, clears quotes and ignores messages from the previous group', async () => {
    const tagId = ref<number | undefined>(undefined);
    const ungrouped = ref(false);
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const page = mount(defineComponent({
      setup() { state = useRealtimeQuotes(() => ({ market: 'US', tagId: tagId.value, ungrouped: ungrouped.value })); return {}; },
      template: '<div />',
    }));
    const first = MockWebSocket.instances[0]!;
    first.message({ type: 'quotes', generated_at: 'all', quotes: [{ code: 'AAPL', market_type: 'US' }] });
    tagId.value = 12;
    await nextTick();
    expect(first.close).toHaveBeenCalled();
    expect(state.quotes.value).toEqual({});
    expect(MockWebSocket.instances[1]!.url).toContain('market=US&tag_id=12');
    first.message({ type: 'quotes', generated_at: 'stale', quotes: [{ code: 'MSFT', market_type: 'US' }] });
    expect(state.quotes.value).toEqual({});
    tagId.value = undefined;
    ungrouped.value = true;
    await nextTick();
    expect(MockWebSocket.instances[2]!.url).toContain('market=US&ungrouped=true');
    expect(MockWebSocket.instances[2]!.url).not.toContain('tag_id');
    page.unmount();
  });

  it('aborts and rebuilds filtered SSE while keeping the fallback and ignoring old group frames', async () => {
    const tagId = ref<number | undefined>(1);
    const streams: Array<{ signal: AbortSignal; accept: Parameters<typeof marketApi.readMarketEvents>[2] }> = [];
    const sse = vi.spyOn(marketApi, 'readMarketEvents').mockImplementation((_options, signal, accept) => {
      streams.push({ signal, accept });
      return new Promise(() => {});
    });
    let state!: ReturnType<typeof useRealtimeQuotes>;
    const page = mount(defineComponent({
      setup() { state = useRealtimeQuotes(() => ({ market: 'CN', tagId: tagId.value })); return {}; }, template: '<div />',
    }));
    MockWebSocket.instances[0]!.disconnect();
    await vi.advanceTimersByTimeAsync(1_000);
    MockWebSocket.instances[1]!.disconnect();
    tagId.value = 2;
    await nextTick();
    expect(streams[0]!.signal.aborted).toBe(true);
    expect(sse.mock.calls[1]![0]).toEqual({ market: 'CN', tagId: 2 });
    streams[1]!.accept({ type: 'quotes', generated_at: 'group2', quotes: [] });
    streams[0]!.accept({ type: 'quotes', generated_at: 'old', quotes: [] });
    expect(state.lastUpdatedAt.value).toBe('group2');
    expect(MockWebSocket.instances).toHaveLength(2);
    page.unmount();
    expect(streams[1]!.signal.aborted).toBe(true);
  });

});
