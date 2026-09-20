import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue';
import type { BinanceInterval, CryptoKline } from '@/types/binance';

const REST = 'https://data-api.binance.vision/api/v3/klines';
const WS = 'wss://data-stream.binance.vision/ws';
const stream = (interval: BinanceInterval) => `btcusdt@kline_${interval}`;

function restCandle(row: (string | number)[], interval: BinanceInterval): CryptoKline {
  if (row.length < 11 || ![0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].every(i => Number.isFinite(Number(row[i])))
    || [1, 2, 3, 4].some(i => Number(row[i]) <= 0)) throw new Error('Invalid Binance candle');
  return {
    symbol: 'BTCUSDT', source: 'binance', interval,
    openTime: new Date(Number(row[0])).toISOString(), closeTime: new Date(Number(row[6]) + 1).toISOString(),
    open: String(row[1]), high: String(row[2]), low: String(row[3]), close: String(row[4]),
    volume: String(row[5]), quoteVolume: String(row[7]), tradeCount: Number(row[8]),
    takerBuyVolume: String(row[9]), takerBuyQuoteVolume: String(row[10]),
    closed: Number(row[6]) < Date.now(),
  };
}

export function useBinanceBtcMarket() {
  const interval = ref<BinanceInterval>('1m');
  const price = ref<string | null>(null);
  const candles = shallowRef<CryptoKline[]>([]);
  const current = shallowRef<CryptoKline | null>(null);
  const connection = ref<'connecting' | 'live' | 'reconnecting'>('connecting');
  const loading = ref(true);
  const restError = ref<string | null>(null);
  const wsError = ref<string | null>(null);
  let stopped = false;
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let request: AbortController | undefined;
  let generation = 0;
  let id = 0;
  let subscribed: BinanceInterval | null = null;
  // Retain only events received while REST is in flight so stale HTTP cannot overwrite them.
  let buffered = new Map<string, CryptoKline>();

  function apply(row: CryptoKline) {
    const latest = current.value ?? candles.value.at(-1);
    if (latest && row.openTime < latest.openTime) return;
    if (latest?.openTime === row.openTime && latest.closed && !row.closed) return;
    if (row.closed) {
      const rows = new Map(candles.value.map(bar => [bar.openTime, bar]));
      rows.set(row.openTime, row);
      candles.value = [...rows.values()].sort((a, b) => a.openTime.localeCompare(b.openTime)).slice(-500);
      current.value = null;
    } else current.value = row;
  }

  function subscribe() {
    if (socket?.readyState !== WebSocket.OPEN) return;
    if (subscribed === interval.value) return;
    if (subscribed) socket.send(JSON.stringify({ method: 'UNSUBSCRIBE', params: [stream(subscribed)], id: ++id }));
    socket.send(JSON.stringify({ method: 'SUBSCRIBE', params: [stream(interval.value)], id: ++id }));
    subscribed = interval.value;
  }

  async function refresh() {
    request?.abort();
    const controller = new AbortController();
    request = controller;
    const version = ++generation;
    const selected = interval.value;
    buffered = new Map();
    loading.value = true;
    restError.value = null;
    try {
      const url = `${REST}?symbol=BTCUSDT&interval=${selected}&limit=500`;
      const response = await fetch(url, { signal: controller.signal, credentials: 'omit' });
      if (!response.ok) throw new Error('Binance REST failed');
      const data = await response.json();
      if (!Array.isArray(data) || !data.length) throw new Error('Invalid Binance candles');
      const rows = data.map(row => restCandle(row, selected));
      if (stopped || version !== generation) return;
      candles.value = rows.filter(row => row.closed);
      current.value = rows.find(row => !row.closed) ?? null;
      for (const row of buffered.values()) apply(row);
      if (price.value === null) price.value = rows.at(-1)?.close ?? null;
    } catch {
      if (!stopped && version === generation) restError.value = '行情加载失败，请重试';
    } finally {
      if (!stopped && version === generation) {
        loading.value = false;
        buffered.clear();
        subscribe();
      }
    }
  }

  function reconnect() {
    if (stopped || retry) return;
    connection.value = 'reconnecting';
    retry = setTimeout(() => { retry = undefined; connect(); }, 3000);
  }

  function connect() {
    if (stopped) return;
    try {
      const next = new WebSocket(WS);
      socket = next;
      subscribed = null;
      next.onopen = () => {
        if (stopped || socket !== next) return;
        connection.value = 'live';
        wsError.value = null;
        next.send(JSON.stringify({ method: 'SUBSCRIBE', params: ['btcusdt@aggTrade'], id: ++id }));
        subscribe();
        // Refresh the selected window once after reconnect to fill disconnected chart gaps.
        if (!loading.value) void refresh();
      };
      next.onmessage = event => {
        if (stopped || socket !== next) return;
        try {
          const data = JSON.parse(String(event.data));
          if (data.code !== undefined) { wsError.value = 'Binance 行情订阅失败'; next.close(); return; }
          if (data.s !== 'BTCUSDT') return;
          if (data.e === 'aggTrade' && Number.isFinite(Number(data.p)) && Number(data.p) > 0) price.value = String(data.p);
          if (data.e !== 'kline' || data.k?.i !== interval.value || typeof data.k.x !== 'boolean') return;
          const k = data.k;
          const row = restCandle([k.t, k.o, k.h, k.l, k.c, k.v, k.T, k.q, k.n, k.V, k.Q], interval.value);
          row.closed = k.x === true;
          if (loading.value) buffered.set(row.openTime, row);
          apply(row);
        } catch { /* Ignore malformed events; they must not replace the chart. */ }
      };
      next.onerror = () => { wsError.value = 'Binance 连接中断，正在重连'; next.close(); };
      next.onclose = () => {
        if (socket !== next) return;
        socket = null;
        subscribed = null;
        reconnect();
      };
    } catch { wsError.value = 'Binance 连接失败，正在重连'; reconnect(); }
  }

  watch(interval, () => {
    candles.value = [];
    current.value = null;
    void refresh();
  }, { flush: 'sync' });
  onMounted(() => { void refresh(); connect(); });
  onUnmounted(() => {
    stopped = true;
    generation++;
    request?.abort();
    clearTimeout(retry);
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      socket.close();
      socket = null;
    }
  });
  return { interval, price, candles, current, connection, loading, restError, wsError, refresh };
}
