<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { dispose, init, type Chart, type OverlayCreate, type KLineData,
  type CandleTooltipLegendsCustomCallback } from 'klinecharts';
import { useTheme } from '@/composables/useTheme';

const props = defineProps<{
  symbol: string;
  period: '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w' | '1M';
  pricePrecision?: number;
  bars: KLineData[];
  current?: KLineData | null;
  sourceKey?: string;
  overlays?: OverlayCreate[];
}>();
const element = ref<HTMLElement>();
const { resolvedTheme } = useTheme();
let chart: Chart | null = null;
let observer: ResizeObserver | undefined;
let pushBar: ((bar: KLineData) => void) | undefined;

const candleTooltipLegends: CandleTooltipLegendsCustomCallback = ({ current }, styles) => {
  const { defaultValue, color } = styles.tooltip.legend;
  const { upColor, downColor, noChangeColor } = styles.bar;
  let changeText = defaultValue;
  let amplitudeText = defaultValue;
  let changeColor = color;
  if (current && Number.isFinite(current.open) && current.open > 0) {
    // Both percentages describe this candle; the built-in {change} uses the previous close.
    const change = (current.close - current.open) / current.open * 100;
    const amplitude = (current.high - current.low) / current.open * 100;
    if (Number.isFinite(change)) {
      changeText = `${change > 0 ? '+' : ''}${change.toFixed(2)}%`;
      changeColor = change > 0 ? upColor : change < 0 ? downColor : noChangeColor;
    }
    if (Number.isFinite(amplitude)) amplitudeText = `${amplitude.toFixed(2)}%`;
  }
  return [
    { title: '时间', value: '{time}' },
    { title: '开盘', value: '{open}' },
    { title: '最高', value: '{high}' },
    { title: '最低', value: '{low}' },
    { title: '收盘', value: '{close}' },
    { title: '涨跌', value: { text: changeText, color: changeColor } },
    { title: '振幅', value: amplitudeText },
    { title: '成交量', value: '{volume}' },
  ];
};

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
      upWickColor: upColor, downWickColor: downColor }, priceMark: { last: colors },
    tooltip: { showRule: 'follow_cross', showType: 'rect',
      legend: { defaultValue: '--', template: candleTooltipLegends } } },
    indicator: { bars: [colors] },
  });
}
function destroy() {
  pushBar = undefined;
  if (element.value && chart) dispose(element.value);
  chart = null;
}
function applyOverlays() {
  if (!chart || !props.overlays) return;
  chart.removeOverlay({ groupId: 'strategy-markers' });
  if (props.overlays.length) chart.createOverlay(props.overlays);
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
  const periods = {
    '1m': { type: 'minute', span: 1 }, '5m': { type: 'minute', span: 5 },
    '15m': { type: 'minute', span: 15 }, '1h': { type: 'hour', span: 1 },
    '4h': { type: 'hour', span: 4 }, '1d': { type: 'day', span: 1 },
    '1w': { type: 'week', span: 1 }, '1M': { type: 'month', span: 1 },
  } as const;
  chart.setPeriod(periods[props.period]);
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
  applyOverlays();
}
watch(() => props.overlays, applyOverlays);
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
