<script setup lang="ts">
import { computed } from 'vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import type { BinanceInterval, CryptoKline } from '@/types/binance';

const props = defineProps<{ interval?: BinanceInterval; candles: CryptoKline[]; current: CryptoKline | null }>();
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
</script>

<template>
  <MarketKLineChart
    symbol="BTCUSDT"
    :period="interval ?? '1m'"
    :price-precision="2"
    :bars="bars"
    :current="current"
    data-testid="btc-kline-chart"
  />
</template>
