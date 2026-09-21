<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { CryptoSnapshot } from '@/types/crypto';
import { btcMarkers } from './btcMarkers';
import { tradeMarkerOverlays } from '@/components/market-data/tradeMarkerOverlay';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import type { BinanceInterval, CryptoKline } from '@/types/binance';
import type { TradeMarker } from '@/lib/tradeMarkers';

const props = defineProps<{ strategyKey?: string; strategyName?: string; signals?: CryptoSnapshot[]; interval?: BinanceInterval; candles: CryptoKline[]; current: CryptoKline | null }>();
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
const selected = ref<TradeMarker | null>(null);
watch(() => props.strategyKey, () => { selected.value = null; });
const markers = computed(() => {
  const rows = [...props.candles, ...(props.current ? [props.current] : [])];
  return btcMarkers(props.signals ?? [], rows, props.strategyKey);
});
const overlays = computed(() => tradeMarkerOverlays(markers.value, timestamp => {
  const bar = [...bars.value, ...(current.value ? [current.value] : [])].find(item => item.timestamp === timestamp);
  return bar?.close ?? Number(props.signals?.[0]?.price ?? 0);
}, marker => { selected.value = marker; }));
</script>

<template>
  <p class="mb-2 text-xs text-muted-foreground">
    策略 BST / Strategy Signal · {{ strategyName ?? strategyKey ?? '当前策略' }}（不是真实成交）
  </p>
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
    <strong>{{ strategyName ?? strategyKey }} · 策略 BST {{ selected.type }}</strong>
    <p
      v-for="(item, index) in selected.operations"
      :key="index"
    >
      {{ item.executedAt }} {{ item.label || item.side }} {{ item.price }} USDT
    </p>
  </div>
</template>
