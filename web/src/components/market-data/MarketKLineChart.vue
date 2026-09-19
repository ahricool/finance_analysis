<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { dispose, init, type Chart, type KLineData } from 'klinecharts';
import { useTheme } from '@/composables/useTheme';

const props = defineProps<{
  symbol: string;
  period: '1m' | '1d';
  pricePrecision?: number;
  bars: KLineData[];
  current?: KLineData | null;
  sourceKey?: string;
}>();
const element = ref<HTMLElement>();
const { resolvedTheme } = useTheme();
let chart: Chart | null = null;
let observer: ResizeObserver | undefined;
let pushBar: ((bar: KLineData) => void) | undefined;

function liveBar() {
  const bar = props.current;
  const last = props.bars.at(-1);
  return bar && (!last || bar.timestamp >= last.timestamp) ? bar : null;
}
function styles() {
  if (!chart) return;
  chart.setStyles(resolvedTheme.value);
  const dark = resolvedTheme.value === 'dark';
  const upColor = dark ? '#e86464' : '#dc2626';
  const downColor = dark ? '#39b77a' : '#16854e';
  const colors = { upColor, downColor, noChangeColor: '#888888' };
  chart.setStyles({
    candle: { bar: { ...colors, upBorderColor: upColor, downBorderColor: downColor,
      upWickColor: upColor, downWickColor: downColor }, priceMark: { last: colors } },
    indicator: { bars: [colors] },
  });
}
function destroy() {
  pushBar = undefined;
  if (element.value && chart) dispose(element.value);
  chart = null;
}
function initialize() {
  destroy();
  if (!element.value) return;
  chart = init(element.value, { timezone: 'UTC', locale: 'zh-CN' });
  if (!chart) return;
  styles();
  chart.createIndicator('VOL');
  if (props.period === '1d') {
    chart.createIndicator({ name: 'MA', calcParams: [5, 10, 20], paneId: 'candle_pane' });
  }
  // KLineChart synchronizes price-series indicators (including MA) from the symbol precision.
  chart.setSymbol({ ticker: props.symbol, volumePrecision: props.period === '1m' ? 4 : 0,
    ...(props.pricePrecision === undefined ? {} : { pricePrecision: props.pricePrecision }) });
  chart.setPeriod({ type: props.period === '1d' ? 'day' : 'minute', span: 1 });
  chart.setDataLoader({
    getBars: ({ type, callback }) => {
      const bars = new Map(props.bars.map(bar => [bar.timestamp, bar]));
      const current = liveBar();
      if (current) bars.set(current.timestamp, current);
      callback(type === 'init' ? [...bars.values()].sort((a, b) => a.timestamp - b.timestamp) : [], false);
    },
    subscribeBar: ({ callback }) => { pushBar = callback; },
    unsubscribeBar: () => { pushBar = undefined; },
  });
}
watch(() => [props.symbol, props.period, props.sourceKey, props.pricePrecision], initialize);
watch(() => props.bars, () => chart?.resetData());
watch(() => props.current, () => {
  const bar = liveBar();
  if (bar) pushBar?.(bar);
  else chart?.resetData();
});
watch(resolvedTheme, styles);
onMounted(() => {
  initialize();
  observer = new ResizeObserver(() => chart?.resize());
  if (element.value) observer.observe(element.value);
});
onBeforeUnmount(() => { observer?.disconnect(); destroy(); });
</script>

<template>
  <div
    ref="element"
    class="h-80 min-w-0 w-full sm:h-[28rem]"
    role="img"
    :aria-label="`${symbol} ${period} K线，红涨绿跌，时间为UTC，可拖动和缩放查看历史`"
  />
</template>
