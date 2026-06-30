import { marketQuoteKey } from '@/api/realtimeMarket';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import { mount } from '@vue/test-utils';
import { defineComponent } from 'vue';
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
});
