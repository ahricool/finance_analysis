<script setup lang="ts">
import { computed, ref } from 'vue';
import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { CryptoSnapshot } from '@/types/crypto';
import { btcMarkers } from './btcMarkers';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import type { BinanceInterval, CryptoKline } from '@/types/binance';

const props = defineProps<{ signals?: CryptoSnapshot[]; interval?: BinanceInterval; candles: CryptoKline[]; current: CryptoKline | null }>();
function toBar(row: CryptoKline) {
  return { timestamp: Date.parse(row.openTime), open: Number(row.open), high: Number(row.high),
    low: Number(row.low), close: Number(row.close), volume: Number(row.volume), turnover: Number(row.quoteVolume) };
}
const bars = computed(() => props.candles.map(toBar));
const current = computed(() => {
  const row = props.current;
  const latest = props.candles.at(-1);
  return row && !row.closed && (!latest || Date.parse(row.openTime) > Date.parse(latest.openTime)) ? toBar(row) : null;
});

const selected = ref<CryptoSnapshot | null>(null);
registerOverlay<{ label: string; buy: boolean; offset: number }>({
  name: 'btcSignal', totalStep: 1, needDefaultPointFigure: false,
  needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
  createPointFigures: ({ coordinates, overlay }) => {
    const point = coordinates[0];
    if (!point) return [];
    const { label, buy, offset } = overlay.extendData;
    return [{ type: 'text', attrs: { x: point.x, y: point.y + (buy ? 18 + offset : -18 - offset), text: label, align: 'center', baseline: 'middle' },
      styles: { color: buy ? '#dc2626' : '#16854e', size: 12, weight: 'bold', backgroundColor: '#ffffff', paddingLeft: 3, paddingRight: 3 } }];
  },
});
const overlays = computed<OverlayCreate[]>(() => {
  const rows = [...props.candles, ...(props.current ? [props.current] : [])];
  const offsets = new Map<number, number>();
  return btcMarkers(props.signals ?? [], rows, props.interval ?? '1m').map(({ signal, timestamp }) => {
    const offset = offsets.get(timestamp) ?? 0;
    offsets.set(timestamp, offset + 16);
    return { name: 'btcSignal', id: `btc-${signal.evaluatedAt}`, groupId: 'strategy-markers', lock: true,
      points: [{ timestamp, value: Number(signal.price) }],
      extendData: { label: signal.action === 'BUY' ? '↑ BUY' : '↓ EXIT', buy: signal.action === 'BUY', offset },
      onClick: () => { selected.value = signal; return true; } };
  });
});
</script>

<template>
  <MarketKLineChart
    symbol="BTCUSDT"
    :period="interval ?? '1m'"
    :price-precision="2"
    :overlays="overlays"
    :bars="bars"
    :current="current"
    data-testid="btc-kline-chart"
  />
  <div
    v-if="selected"
    class="mt-3 rounded border p-3 text-sm"
    data-testid="btc-signal-detail"
  >
    <strong>{{ selected.action }} · {{ selected.evaluatedAt }} · {{ selected.price }} USDT</strong>
    <p>仓位 {{ selected.positionBefore == null ? '未知' : `${Number(selected.positionBefore) * 100}%` }} → {{ selected.positionAfter == null ? '未知' : `${Number(selected.positionAfter) * 100}%` }} · {{ selected.regime }} · {{ selected.setup }}</p>
    <p>{{ selected.reason }}</p>
  </div>
</template>
