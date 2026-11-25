import { onBeforeUnmount, ref, watch, type Ref } from 'vue';
import { contractStreamUrl, type MarketSnapshot } from '@/api/contracts';
import { redirectToLogin } from '@/api';

export function useContractMarket(symbol: Ref<string>, interval: Ref<'1d' | '1m'>, receive: (snapshot: MarketSnapshot) => void) {
  const status = ref('连接中');
  let socket: WebSocket | null = null;
  let events: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let failures = 0;
  let fallback = false;

  function clear() {
    clearTimeout(timer);
    clearTimeout(watchdog);
    if (socket) {
      socket.onclose = socket.onerror = socket.onmessage = null;
      socket.close();
      socket = null;
    }
    events?.close();
    events = null;
  }

  function connect() {
    const current = ++generation;
    clear();
    status.value = fallback ? 'SSE 连接中' : 'WS 连接中';
    function valid() {
      return current === generation;
    }
    function accept(raw: string, transport: string) {
      if (!valid()) return;
      try {
        const snapshot = JSON.parse(raw) as MarketSnapshot;
        if (!Array.isArray(snapshot.items) || (snapshot.symbol ?? '') !== symbol.value) return;
        status.value = transport + ' 已连接';
        failures = 0;
        if (!valid()) return;
        clearTimeout(watchdog);
        watchdog = setTimeout(retry, 20_000);
        receive(snapshot);
      } catch {
        retry();
      }
    }
    function retry() {
      if (!valid()) return;
      ++generation;
      clear();
      if (!fallback && ++failures >= 2) fallback = true;
      status.value = '行情重连中';
      timer = setTimeout(connect, 1500);
    }
    watchdog = setTimeout(retry, 12_000);
    if (fallback) {
      try {
        events = new EventSource(contractStreamUrl('events', symbol.value, interval.value), { withCredentials: true });
        events.onmessage = event => accept(event.data, 'SSE');
        events.onerror = retry;
      } catch { retry(); }
    } else {
      try {
        socket = new WebSocket(contractStreamUrl('ws', symbol.value, interval.value));
        socket.onmessage = event => accept(event.data, 'WS');
        socket.onerror = retry;
        socket.onclose = event => {
          if (!valid()) return;
          if (event.code === 4401) {
            ++generation;
            clear();
            status.value = '登录已失效';
            redirectToLogin();
          } else retry();
        };
      } catch { retry(); }
    }
  }
  watch([symbol, interval], connect, { immediate: true });
  onBeforeUnmount(() => { ++generation; clear(); });
  return { status };
}
