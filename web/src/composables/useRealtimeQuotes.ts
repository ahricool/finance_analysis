import {
  buildMarketWebSocketUrl,
  isRealtimeQuoteMessage,
  marketQuoteKey,
  type RealtimeConnectionStatus,
  type RealtimeQuote,
} from '@/api/realtimeMarket';
import type { MarketType } from '@/api/watchList';
import { onMounted, onUnmounted, ref, shallowRef } from 'vue';

const INITIAL_RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

export function useRealtimeQuotes() {
  const quotes = shallowRef<Record<string, RealtimeQuote>>({});
  const status = ref<RealtimeConnectionStatus>('connecting');
  const lastUpdatedAt = ref<string | null>(null);
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let reconnectAttempts = 0;
  let stopped = false;

  function clearReconnectTimer() {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer !== null) return;
    status.value = 'reconnecting';
    const delay = Math.min(INITIAL_RECONNECT_DELAY_MS * 2 ** reconnectAttempts, MAX_RECONNECT_DELAY_MS);
    reconnectAttempts += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (stopped || socket) return;
    status.value = reconnectAttempts ? 'reconnecting' : 'connecting';
    const current = new WebSocket(buildMarketWebSocketUrl());
    socket = current;

    current.onopen = () => {
      reconnectAttempts = 0;
      status.value = 'connected';
    };
    current.onmessage = (event) => {
      try {
        const message: unknown = JSON.parse(String(event.data));
        if (!isRealtimeQuoteMessage(message)) return;
        quotes.value = Object.fromEntries(
          message.quotes.map((quote) => [marketQuoteKey(quote.code, quote.market_type), quote]),
        );
        lastUpdatedAt.value = message.generated_at;
      } catch {
        // Ignore malformed frames; the next five-second snapshot replaces all state.
      }
    };
    current.onerror = () => {
      if (!stopped) status.value = 'reconnecting';
    };
    current.onclose = (event) => {
      if (socket === current) socket = null;
      if (stopped) return;
      if (event.code === 4401 || event.code === 4403) {
        status.value = 'unauthorized';
        return;
      }
      scheduleReconnect();
    };
  }

  function disconnect() {
    stopped = true;
    clearReconnectTimer();
    const current = socket;
    socket = null;
    if (current && current.readyState < WebSocket.CLOSING) {
      current.close(1000, 'Page closed');
    }
  }

  function getQuote(code: string, marketType: MarketType): RealtimeQuote | undefined {
    return quotes.value[marketQuoteKey(code, marketType)];
  }

  onMounted(connect);
  onUnmounted(disconnect);

  return { quotes, status, lastUpdatedAt, getQuote, connect, disconnect };
}
