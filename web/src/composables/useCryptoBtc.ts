import { onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { cryptoApi, cryptoWebSocketUrl, parseCryptoMessage } from '@/api/crypto';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { CryptoKline, CryptoOverview, CryptoSnapshot, CryptoStatus } from '@/types/crypto';

export function useCryptoBtc() {
  const candles = shallowRef<CryptoKline[]>([]);
  const current = shallowRef<CryptoKline | null>(null);
  const overview = shallowRef<CryptoOverview | null>(null);
  const signals = shallowRef<CryptoSnapshot[]>([]);
  const status = shallowRef<CryptoStatus | null>(null);
  const connection = ref<'connecting' | 'websocket' | 'http_fallback' | 'unauthorized'>('connecting');
  const loading = ref(true);
  const error = shallowRef<ParsedApiError | null>(null);
  let stopped = false;
  let socket: WebSocket | null = null;
  let pollTimer: ReturnType<typeof setInterval> | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  let polling = false;

  function mergeClosed(rows: CryptoKline[]) {
    const map = new Map(candles.value.map(row => [Date.parse(row.openTime), row]));
    let changed = false;
    for (const row of rows) {
      if (!row.closed) continue;
      const key = Date.parse(row.openTime);
      if (JSON.stringify(map.get(key)) !== JSON.stringify(row)) { map.set(key, row); changed = true; }
    }
    if (changed) candles.value = [...map.values()].sort((a, b) => Date.parse(a.openTime) - Date.parse(b.openTime)).slice(-1000);
  }

  function mergeSignals(rows: CryptoSnapshot[]) {
    const map = new Map(signals.value.map(row => [Date.parse(row.evaluatedAt), row]));
    for (const row of rows) map.set(Date.parse(row.evaluatedAt), row);
    signals.value = [...map.values()].sort((a, b) => Date.parse(b.evaluatedAt) - Date.parse(a.evaluatedAt)).slice(0, 50);
  }

  function applyStatus(value: CryptoStatus) {
    if (value.lastUpdateTime && status.value?.lastUpdateTime
        && Date.parse(value.lastUpdateTime) < Date.parse(status.value.lastUpdateTime)) return;
    status.value = value;
    mergeClosed(value.recentClosed ?? []);
    const row = value.latestCandle;
    if (row && (!current.value || Date.parse(row.openTime) >= Date.parse(current.value.openTime))) {
      current.value = row;
      mergeClosed([row]);
    }
    const snapshot = value.strategyLatestState;
    if (snapshot && (!signals.value[0] || Date.parse(snapshot.evaluatedAt) > Date.parse(signals.value[0].evaluatedAt))) {
      signals.value = [snapshot, ...signals.value].slice(0, 50);
      if (overview.value) overview.value = { ...overview.value, strategy: snapshot };
    }
  }

  async function refresh(limit = 5) {
    if (polling || stopped) return;
    polling = true;
    try {
      const [bars, info, recent] = await Promise.all([cryptoApi.klines(limit), cryptoApi.overview(), cryptoApi.signals()]);
      if (stopped) return;
      mergeClosed(bars.items);
      mergeSignals([...recent.items, ...(info.strategy ? [info.strategy] : [])]);
      overview.value = { ...info, strategy: signals.value[0] ?? info.strategy };
      applyStatus(info.market);
      error.value = null;
    } catch (reason) {
      if (!stopped) error.value = getParsedApiError(reason);
    } finally {
      polling = false;
      loading.value = false;
    }
  }

  function clearSocket() {
    clearTimeout(watchdog);
    const old = socket;
    socket = null;
    if (old) {
      old.onopen = old.onmessage = old.onerror = old.onclose = null;
      old.close();
    }
  }

  function fallback() {
    if (stopped || connection.value === 'unauthorized') return;
    clearSocket();
    connection.value = 'http_fallback';
    if (!pollTimer) {
      void refresh();
      pollTimer = setInterval(() => void refresh(), 60_000);
    }
    if (!reconnectTimer) reconnectTimer = setTimeout(() => { reconnectTimer = undefined; connect(); }, 15_000);
  }

  function armWatchdog() {
    clearTimeout(watchdog);
    watchdog = setTimeout(fallback, 15_000);
  }

  function connect() {
    if (stopped || socket || connection.value === 'unauthorized') return;
    try {
      const next = new WebSocket(cryptoWebSocketUrl());
      socket = next;
      armWatchdog();
      next.onmessage = event => {
        if (socket !== next || stopped) return;
        try {
          const message = parseCryptoMessage(String(event.data));
          if (!message) return;
          const recovered = connection.value !== 'websocket';
          connection.value = 'websocket';
          clearInterval(pollTimer); pollTimer = undefined;
          clearTimeout(reconnectTimer); reconnectTimer = undefined;
          armWatchdog();
          applyStatus(message);
          if (recovered) void refresh(1000);
        } catch { /* malformed frames never count as recovery */ }
      };
      next.onerror = fallback;
      next.onclose = event => {
        if (event.code === 4401 || event.code === 4403) {
          clearSocket();
          clearInterval(pollTimer); pollTimer = undefined;
          clearTimeout(reconnectTimer); reconnectTimer = undefined;
          connection.value = 'unauthorized';
        } else fallback();
      };
    } catch { fallback(); }
  }

  onMounted(() => { void refresh(1000); connect(); });
  onUnmounted(() => {
    stopped = true;
    clearInterval(pollTimer);
    clearTimeout(reconnectTimer);
    clearSocket();
  });
  return { candles, current, overview, signals, status, connection, loading, error, refresh };
}
