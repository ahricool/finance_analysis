<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { dispose, init, utils, type FormatDate, type Chart, type OverlayCreate, type KLineData,
  type CandleTooltipLegendsCustomCallback } from 'klinecharts';
import { useTheme } from '@/composables/useTheme';
import { readMarketCanvasColors } from '@/utils/marketColors';

const props = defineProps<{
  symbol: string;
  period: '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w' | '1M';
  pricePrecision?: number;
  bars: KLineData[];
  current?: KLineData | null;
  sourceKey?: string;
  focusTimestamp?: number;
  focusRequest?: number;
  overlays?: OverlayCreate[];
  timezone?: string;
  referencePrice?: number;
  session?: { open: number; close: number; breakStart: number; breakEnd: number };
}>();
const element = ref<HTMLElement>();
const { resolvedTheme } = useTheme();
let chart: Chart | null = null;
let observer: ResizeObserver | undefined;
let appliedOverlayIds: string[] = [];
let pushBar: ((bar: KLineData) => void) | undefined;
let fitFrame: number | undefined;

const candleTooltipLegends: CandleTooltipLegendsCustomCallback = ({ prev, current }, styles) => {
  const { defaultValue, color } = styles.tooltip.legend;
  const { upColor, downColor, noChangeColor } = styles.bar;
  let changeText = defaultValue;
  let amplitudeText = defaultValue;
  let changeColor = color;
  const baseline = props.referencePrice ?? prev?.close;
  if (current && baseline != null && Number.isFinite(baseline) && baseline > 0) {
    // Daily candles use the previous trading day’s close as the baseline.
    const change = (current.close - baseline) / baseline * 100;
    const amplitude = (current.high - current.low) / baseline * 100;
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
  const { up, down, muted } = readMarketCanvasColors(dark);
  const colors = { upColor: up, downColor: down, noChangeColor: muted };
  chart.setStyles({
    candle: { bar: { ...colors, upBorderColor: up, downBorderColor: down,
      upWickColor: up, downWickColor: down }, priceMark: { last: colors },
    tooltip: { showRule: 'follow_cross', showType: 'rect',
      legend: { defaultValue: '--', template: candleTooltipLegends } } },
    indicator: { bars: [colors] },
  });
}
function destroy() {
  if (fitFrame != null) cancelAnimationFrame(fitFrame);
  pushBar = undefined;
  if (element.value && chart) dispose(element.value);
  chart = null;
  appliedOverlayIds = [];
}
function applyReferenceRange() {
  if (!chart || props.referencePrice == null) return;
  chart.overrideYAxis({ paneId: 'candle_pane', createRange: ({ defaultRange }) => {
    const reference = props.referencePrice;
    if (reference == null || !Number.isFinite(reference) || reference <= 0) return defaultRange;
    const low = Math.min(defaultRange.from, reference);
    const high = Math.max(defaultRange.to, reference);
    const padding = Math.max(high - low, reference * 0.002) * 0.05;
    const from = low - padding, to = high + padding, range = to - from;
    return { from, to, range, realFrom: from, realTo: to, realRange: range,
      displayFrom: from, displayTo: to, displayRange: range };
  } });
}
function fitSession() {
  if (!chart || !props.session) return;
  if (fitFrame != null) cancelAnimationFrame(fitFrame);
  fitFrame = requestAnimationFrame(() => {
    if (!chart || !props.session) return;
    const { open, close, breakStart, breakEnd } = props.session;
    const width = chart.getSize('candle_pane', 'main')?.width;
    const last = liveBar() ?? props.bars.at(-1);
    if (!width || !last) return;
    // Reserve future trading minutes without adding fabricated OHLC or volume rows.
    const total = (close - open - (breakEnd - breakStart)) / 60_000;
    const remaining = Math.max(0, (close - last.timestamp - Math.max(0, breakEnd - Math.max(last.timestamp, breakStart))) / 60_000 - 1);
    const space = width / (total + 2);
    chart.setBarSpace(space);
    chart.setOffsetRightDistance((remaining + 1) * space);
  });
}
function applyOverlays() {
  if (!chart) return;
  // Remove only overlays owned by this prop, including groups removed in the new value.
  // User drawings and other chart-owned overlays must survive updates.
  for (const id of appliedOverlayIds) chart.removeOverlay({ id });
  appliedOverlayIds = [];
  if (props.overlays?.length) {
    const created = chart.createOverlay(props.overlays);
    appliedOverlayIds = (Array.isArray(created) ? created : [created]).filter((id): id is string => id != null);
  }
}
function focusOnTimestamp(timestamp: number) {
  if (!chart) return;
  chart.scrollToTimestamp(timestamp);
  const width = chart.getSize('candle_pane', 'main')?.width;
  const point = chart.convertToPixel({ timestamp }, { paneId: 'candle_pane' });
  if (width && !Array.isArray(point) && point.x != null) {
    chart.scrollByDistance(width / 2 - point.x);
  }
}
const formatSessionDate: FormatDate = ({ dateTimeFormat, timestamp, template, type }) => {
  // The library extrapolates wall-clock minutes into empty space, including lunch.
  // Keep future slots empty instead of showing a fabricated crosshair timestamp.
  if (type === 'crosshair' && !props.bars.some(bar => bar.timestamp === timestamp) && liveBar()?.timestamp !== timestamp) return '';
  return utils.formatDate(dateTimeFormat, timestamp, template);
};
function initialize() {
  destroy();
  if (!element.value) return;
  chart = init(element.value, { timezone: props.timezone ?? 'UTC', locale: 'zh-CN',
    ...(props.session ? { formatter: { formatDate: formatSessionDate }, layout: { barSpaceLimit: { min: 0.25, max: 50 } } } : {}) });
  if (!chart) return;
  styles();
  applyReferenceRange();
  if (props.session) {
    chart.setScrollEnabled(false);
    chart.setZoomEnabled(false);
    chart.overrideXAxis({ scrollZoomEnabled: false, createTicks: ({ bounding }) => [
      { coord: 20, value: props.session!.open, text: '09:30' },
      { coord: bounding.width / 2, value: props.session!.breakStart, text: '11:30 / 13:00' },
      { coord: bounding.width - 20, value: props.session!.close, text: '15:00' },
    ] });
  }
  chart.createIndicator('VOL');
  if (['1d', '1w', '1M'].includes(props.period)) {
    chart.createIndicator({ name: 'MA', calcParams: [5, 10, 20], paneId: 'candle_pane' });
  }
  if (props.period === '1m' && props.timezone) {
    chart.createIndicator({ name: 'MA', calcParams: [20], paneId: 'candle_pane' });
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
      if (type === 'init' && props.focusTimestamp != null) {
        focusOnTimestamp(props.focusTimestamp);
      }
      fitSession();
    },
    subscribeBar: ({ callback }) => { pushBar = callback; },
    unsubscribeBar: () => { pushBar = undefined; },
  });
  applyOverlays();
}
watch(() => props.overlays, applyOverlays);
watch(() => [props.focusTimestamp, props.focusRequest], () => {
  const timestamp = props.focusTimestamp;
  if (timestamp != null) focusOnTimestamp(timestamp);
  else chart?.scrollToRealTime();
});
watch(() => [props.symbol, props.period, props.sourceKey, props.pricePrecision, props.timezone, props.session?.open], initialize);
watch(() => props.referencePrice, applyReferenceRange);
watch(() => props.bars, () => { chart?.resetData(); fitSession(); });
watch(() => props.current, () => {
  const bar = liveBar();
  if (bar) pushBar?.(bar);
  else chart?.resetData();
  fitSession();
});
watch(resolvedTheme, styles);
onMounted(() => {
  initialize();
  observer = new ResizeObserver(() => { chart?.resize(); fitSession(); });
  if (element.value) observer.observe(element.value);
});
onBeforeUnmount(() => { observer?.disconnect(); destroy(); });
</script>

<template>
  <div
    ref="element"
    class="h-80 min-w-0 w-full sm:h-[28rem]"
    role="img"
    :aria-label="`${symbol} ${period} K线，红涨绿跌，时间为${timezone ?? 'UTC'}，${session ? '当日09:30至15:00，午休不占交易分钟' : '可拖动和缩放查看历史'}`"
  />
</template>
