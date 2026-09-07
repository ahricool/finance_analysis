<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { CandlestickChart } from 'echarts/charts';
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { CryptoKline } from '@/types/crypto';

use([CanvasRenderer, CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent]);
const props = defineProps<{ candles: CryptoKline[]; current: CryptoKline | null }>();
const chart = ref<InstanceType<typeof VChart>>();
const { resolvedTheme } = useTheme();
const initOptions = { useDirtyRect: true };
let initialized = false;
const option = computed(() => {
  const dark = resolvedTheme.value === 'dark';
  const text = dark ? '#a3a3a3' : '#525252';
  return {
    animation: false,
    useUTC: true,
    grid: { left: 12, right: 16, top: 20, bottom: 62, containLabel: true },
    tooltip: { trigger: 'axis', confine: true },
    xAxis: { type: 'time', axisLabel: { color: text, hideOverlap: true } },
    yAxis: { scale: true, axisLabel: { color: text }, splitLine: { lineStyle: { color: dark ? '#333' : '#eee' } } },
    dataZoom: [{ type: 'inside', start: 85, end: 100 }, { type: 'slider', height: 22, bottom: 10, start: 85, end: 100 }],
    series: ['history', 'current'].map(id => ({
      id, name: id === 'history' ? 'BTCUSDT · 已收盘' : 'BTCUSDT · 当前分钟', type: 'candlestick',
      dimensions: ['time', 'open', 'close', 'low', 'high'],
      encode: { x: 'time', y: ['open', 'close', 'low', 'high'], tooltip: ['open', 'close', 'low', 'high'] },
      itemStyle: { color: dark ? '#e86464' : '#dc2626', color0: dark ? '#39b77a' : '#16854e',
        borderColor: dark ? '#e86464' : '#dc2626', borderColor0: dark ? '#39b77a' : '#16854e' },
      barMaxWidth: 12, data: [],
    })),
  };
});
function value(row: CryptoKline) {
  return [Date.parse(row.openTime), Number(row.open), Number(row.close), Number(row.low), Number(row.high)];
}
function updateCurrent() {
  if (!initialized) return;
  const row = props.current;
  const latest = props.candles.at(-1);
  const show = row && !row.closed && (!latest || Date.parse(row.openTime) > Date.parse(latest.openTime));
  chart.value?.setOption({ series: [{ id: 'current', data: show ? [value(row)] : [] }] });
}
function updateHistory() {
  if (!initialized) return;
  chart.value?.setOption({ series: [{ id: 'history', data: props.candles.map(value) }] });
  updateCurrent();
}
watch(() => props.candles, updateHistory);
watch(() => props.current, updateCurrent);
watch(option, () => { chart.value?.setOption(option.value); updateHistory(); });
onMounted(async () => {
  // vue-echarts defers its initial option commit when autoresize is enabled.
  await nextTick();
  chart.value?.setOption(option.value);
  initialized = true;
  updateHistory();
});
</script>

<template>
  <div
    class="h-80 min-w-0 sm:h-[28rem]"
    data-testid="btc-kline-chart"
  >
    <VChart
      ref="chart"
      :option="option"
      manual-update
      autoresize
      :init-options="initOptions"
      role="img"
      aria-label="BTCUSDT 1分钟K线，红涨绿跌，时间为UTC，可拖动和缩放查看历史"
    />
  </div>
</template>
