import {
  buildMarketWebSocketUrl, marketQuoteKey, MarketStreamAuthError, parseRealtimeQuoteMessage, readMarketEvents,
  type MarketStreamOptions, type RealtimeConnectionStatus, type RealtimeQuote, type RealtimeQuoteMessage,
} from '@/api/realtimeMarket';
import type { HoldingsSummary } from '@/api/holdings';
import { redirectToLogin } from '@/api';
import type { MarketType } from '@/api/watchList';
import { onMounted, onUnmounted, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue';

const CONNECTION_TIMEOUT_MS = 20_000;
const SSE_CONNECTION_TIMEOUT_MS = 60_000;
const SSE_IDLE_TIMEOUT_MS = 30_000;
// Brief tab switches keep the stream; longer absences free the server push loop.
const HIDDEN_DISCONNECT_MS = 60_000;

export function useRealtimeQuotes(options: MaybeRefOrGetter<MarketStreamOptions> = {}) {
  const quotes = shallowRef<Record<string, RealtimeQuote>>({});
  const portfolio = shallowRef<HoldingsSummary | null>(null);
  const status = ref<RealtimeConnectionStatus>('connecting');
  const lastUpdatedAt = ref<string | null>(null);
  let socket: WebSocket | null = null;
  let controller: AbortController | null = null;
  let reconnectTimer: number | null = null;
  let watchdog: number | null = null;
  let failures = 0;
  let useSse = false;
  let sseFailures = 0;
  let stopped = false;
  let generation = 0;
  let hiddenTimer: number | null = null;

  function clearTimers() {
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    if (watchdog !== null) window.clearTimeout(watchdog);
    reconnectTimer = watchdog = null;
  }

  function armWatchdog(expire: () => void, timeout = CONNECTION_TIMEOUT_MS) {
    if (watchdog !== null) window.clearTimeout(watchdog);
    watchdog = window.setTimeout(expire, timeout);
  }

  function accept(message: RealtimeQuoteMessage) {
    quotes.value = Object.fromEntries(message.quotes.map(q => [marketQuoteKey(q.code, q.marketType), q]));
    portfolio.value = message.portfolio;
    lastUpdatedAt.value = message.generatedAt;
  }

  function retry(callback: () => void, sse = false) {
    status.value = sse ? 'sse-reconnecting' : 'reconnecting';
    const delay = sse ? Math.min(5_000 * 2 ** Math.min(sseFailures - 1, 3), 30_000) : 1_000;
    reconnectTimer = window.setTimeout(() => { reconnectTimer = null; callback(); }, delay);
  }

  function connectSse() {
    if (stopped || controller) return;
    status.value = 'sse-reconnecting';
    const current = new AbortController();
    const ownedGeneration = generation;
    controller = current;
    armWatchdog(() => current.abort(), SSE_CONNECTION_TIMEOUT_MS);
    void readMarketEvents(toValue(options), current.signal, message => {
      if (stopped || generation !== ownedGeneration || controller !== current) return;
      accept(message);
      status.value = 'sse';
      sseFailures = 0;
    }, () => {
      if (stopped || generation !== ownedGeneration || controller !== current) return;
      status.value = 'sse';
      armWatchdog(() => current.abort(), SSE_IDLE_TIMEOUT_MS);
    }).catch(error => {
      if (stopped || generation !== ownedGeneration || controller !== current) return;
      clearTimers();
      controller = null;
      if (error instanceof MarketStreamAuthError) unauthorized(error.status === 401);
      else { sseFailures += 1; retry(connectSse, true); }
    });
  }

  function connect() {
    if (stopped || socket || controller || reconnectTimer !== null || status.value === 'unauthorized') return;
    if (useSse) { connectSse(); return; }
    status.value = failures ? 'reconnecting' : 'connecting';
    let current: WebSocket;
    try { current = new WebSocket(buildMarketWebSocketUrl(toValue(options))); }
    catch { failed(); return; }
    socket = current;
    function failed() {
      if (stopped || (current && socket !== current)) return;
      clearTimers();
      socket = null;
      if (current && current.readyState < WebSocket.CLOSING) current.close();
      failures += 1;
      if (failures >= 2) { useSse = true; connectSse(); }
      else retry(connect);
    }
    armWatchdog(failed);
    current.onopen = () => {
      if (socket === current && !stopped) status.value = 'connected';
    };
    current.onmessage = event => {
      if (socket !== current || stopped) return;
      let payload: unknown;
      try { payload = JSON.parse(String(event.data)); } catch { return; }
      const message = parseRealtimeQuoteMessage(payload);
      if (!message) return;
      failures = 0;
      accept(message);
      status.value = 'connected';
      armWatchdog(failed);
    };
    current.onerror = failed;
    current.onclose = event => {
      if (socket !== current || stopped) return;
      if (event.code === 4401 || event.code === 4403) {
        clearTimers(); socket = null; unauthorized(event.code === 4401);
      } else failed();
    };
  }

  // 4401 / SSE 401 mean the session is gone: recover the same way as an HTTP 401.
  function unauthorized(sessionExpired: boolean) {
    status.value = 'unauthorized';
    if (sessionExpired) redirectToLogin();
  }

  function release() {
    generation++;
    clearTimers();
    const current = socket;
    socket = null;
    if (current && current.readyState < WebSocket.CLOSING) current.close(1000, 'Page closed');
    controller?.abort();
    controller = null;
  }

  function disconnect() { stopped = true; clearHiddenTimer(); release(); }
  function clearHiddenTimer() {
    if (hiddenTimer !== null) window.clearTimeout(hiddenTimer);
    hiddenTimer = null;
  }
  function onVisibility() {
    if (stopped || status.value === 'unauthorized') return;
    if (document.visibilityState === 'hidden') {
      if (hiddenTimer === null && status.value !== 'paused') hiddenTimer = window.setTimeout(() => {
        hiddenTimer = null;
        release();
        status.value = 'paused';
      }, HIDDEN_DISCONNECT_MS);
      return;
    }
    clearHiddenTimer();
    if (status.value === 'paused') { status.value = 'connecting'; connect(); }
  }
  function getQuote(code: string, marketType: MarketType): RealtimeQuote | undefined {
    return quotes.value[marketQuoteKey(code, marketType)];
  }

  watch(() => JSON.stringify(toValue(options)), () => {
    release();
    quotes.value = {}; portfolio.value = null; lastUpdatedAt.value = null;
    sseFailures = 0;
    // Once downgraded, stay on SSE for this page's lifetime, including market switches.
    if (!stopped && status.value !== 'paused') connect();
  });
  onMounted(() => { document.addEventListener('visibilitychange', onVisibility); connect(); });
  onUnmounted(() => { document.removeEventListener('visibilitychange', onVisibility); disconnect(); });
  return { quotes, portfolio, status, lastUpdatedAt, getQuote, connect, disconnect };
}
