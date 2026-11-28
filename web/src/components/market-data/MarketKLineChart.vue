<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { dispose, init, utils, type FormatDate, type Chart, type OverlayCreate, type KLineData,
  type CandleTooltipLegendsCustomCallback } from 'klinecharts';
import { useTheme } from '@/composables/useTheme';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { useMinuteForecast } from '@/composables/useMinuteForecast';
import { Button } from '@/components/ui/button';
import { readMarketCanvasColors } from '@/utils/marketColors';
import type { DailyForecast } from '@/api/marketData';
import { DAILY_FORECAST_OVERLAY_ID, MINUTE_FORECAST_OVERLAY_ID, forecastOverlay } from './kronosForecastOverlay';
import KronosForecastPanel from './KronosForecastPanel.vue';
import type { ChartAnnotation } from './chartAnnotation';
import { sessionStyles } from './tradingSessionOverlay';
import type { TradeSession } from '@/api/intradayMarket';

const props = defineProps<{
  symbol: string;
  contractForecast?: boolean;
  disableForecast?: boolean;
  period: '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w' | '1M' | '1y';
  pricePrecision?: number;
  bars: KLineData[];
  dailyForecast?: DailyForecast | null;
  current?: KLineData | null;
  liveSnapshot?: boolean;
  sourceKey?: string;
  focusTimestamp?: number;
  focusRequest?: number;
  overlays?: ChartAnnotation[];
  timezone?: string;
  referencePrice?: number;
  fullMinuteWindow?: boolean;
}>();
const element = ref<HTMLElement>();
const { resolvedTheme } = useTheme();
const now = useCurrentTime(3_000);
const forecastResponse = useMinuteForecast(() => props.symbol, () => !props.disableForecast && props.period === '1m' && props.bars.length > 0, props.contractForecast);
const showForecast = ref(true);
const forecast = computed(() => {
  const value = forecastResponse.value?.forecast;
  return props.period === '1m' && value?.symbol === props.symbol ? value : null;
});
const MINUTE_MS = 60_000;
const future = computed(() => {
  const value = forecast.value;
  const last = props.bars.at(-1)?.timestamp;
  if (!value || last == null || !props.bars.some(bar => bar.timestamp === value.anchor)) return [];
  if (value.closeReplay) return value.anchor === last && (props.current?.timestamp ?? last) <= last ? value.bars : [];
  return value.bars.filter(bar => bar.timestamp > last && bar.timestamp + MINUTE_MS > now.value.getTime());
});
const minuteSlots = computed(() => {
  const value = forecast.value;
  const latest = liveBar() ?? props.bars.at(-1);
  if (!latest || !value?.sessionClose || value.closeReplay || !props.bars.some(bar => bar.timestamp === value.anchor)) return null;
  const targets = value.bars.filter(bar => bar.timestamp > latest.timestamp);
  const positions = new Map(targets.map((bar, index) => [bar.timestamp, latest.timestamp + (index + 1) * MINUTE_MS]));
  return { base: latest.timestamp, targets, positions };
});
const minuteProjection = computed(() => future.value.map(bar => {
  const slot = minuteSlots.value?.positions.get(bar.timestamp);
  return slot == null ? bar : { ...bar, timestamp: slot };
}));
const dayTimestamp = (day: string) => Date.parse(`${day}T00:00:00Z`);
const DAY_MS = 86_400_000;
const lastDailyTimestamp = computed(() => props.bars.at(-1)?.timestamp);
const dailyForecast = computed(() => {
  const value = props.dailyForecast;
  return props.period === '1d' && value?.symbol === props.symbol &&
    props.bars.some(bar => bar.timestamp === dayTimestamp(value.anchorDate)) ? value : null;
});
const dailyFuture = computed(() => {
  const value = dailyForecast.value;
  const last = lastDailyTimestamp.value;
  if (!value || last == null) return [];
  return value.bars.map(({ tradeDate, ...bar }) => ({ ...bar, timestamp: dayTimestamp(tradeDate) }))
    .filter(bar => bar.timestamp > last);
});
const dailyProjection = computed(() => {
  const last = lastDailyTimestamp.value;
  return last == null ? [] : dailyFuture.value.map((bar, index) => ({
    ...bar, timestamp: last + (index + 1) * DAY_MS,
  }));
});
const futurePrices = computed(() => props.period === '1d' ? dailyFuture.value : future.value);
const forecastOverlayKey = computed(() => {
  const daily = dailyForecast.value;
  if (daily && dailyFuture.value.length) {
    return `${daily.symbol}:${daily.weightsRevision}:${daily.generatedAt}:${lastDailyTimestamp.value}:${dailyFuture.value.map(bar => bar.timestamp).join(',')}`;
  }
  const value = forecast.value;
  return value && minuteProjection.value.length
    ? `${value.symbol}:${value.weightsRevision}:${value.generatedAt}:${minuteProjection.value.map(bar => bar.timestamp).join(',')}`
    : '';
});
let chart: Chart | null = null;
let observer: ResizeObserver | undefined;
let appliedOverlayIds: string[] = [];
let drawnForecastId: string | undefined;
let followSession = true;
let fittedMinuteForecast = false;
let restoringViewport = false;
const hoveredId = ref<string>();
const hoveredHint = ref('');
const hintPosition = ref<{ left?: string; right?: string; top: string; transform?: string }>();
const forecastAnnotation = computed(() => {
  if (!showForecast.value) return null;
  const dark = resolvedTheme.value === 'dark';
  if (dailyForecast.value && dailyProjection.value.length) {
    return forecastOverlay(DAILY_FORECAST_OVERLAY_ID, 'Kronos 日 K 预测', dailyProjection.value, dark);
  }
  const value = forecast.value;
  if (!value || !future.value.length) return null;
  return forecastOverlay(MINUTE_FORECAST_OVERLAY_ID, value.closeReplay ? 'Kronos 收盘试算' : 'Kronos 分钟线预测',
    minuteProjection.value, dark);
});
const hoverHint = computed(() => {
  if (!hoveredId.value) return undefined;
  const current = hoveredId.value === forecastAnnotation.value?.id
    ? forecastAnnotation.value : props.overlays?.find(item => item.id === hoveredId.value);
  return current?.hint === hoveredHint.value ? current.hint : undefined;
});
function clearHover() { hoveredId.value = undefined; }
function withHover(annotation: ChartAnnotation): OverlayCreate {
  if (!annotation.hint) return annotation;
  const { hint, ...overlay } = annotation;
  return { ...overlay,
    onMouseMove: event => {
      const pane = event.chart.getSize('candle_pane', 'main');
      if (pane && event.x != null && event.y != null) {
        const x = pane.left + event.x;
        const above = event.y > pane.height / 2;
        const width = element.value?.clientWidth ?? pane.width;
        const horizontal = x < width / 2
          ? { left: `${x + 12}px` }
          : { right: `${width - x + 12}px` };
        hintPosition.value = { ...horizontal, top: `${pane.top + event.y + (above ? -12 : 12)}px`,
          transform: above ? 'translateY(-100%)' : undefined };
        hoveredId.value = overlay.id;
        hoveredHint.value = hint;
      }
      overlay.onMouseMove?.(event);
    },
    onMouseLeave: event => { if (hoveredId.value === overlay.id) clearHover(); overlay.onMouseLeave?.(event); },
  };
}
let pushBar: ((bar: KLineData) => void) | undefined;

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
    ...(props.fullMinuteWindow && current?.tradeSession && sessionStyles[current.tradeSession as TradeSession]
      ? [{ title: '时段', value: sessionStyles[current.tradeSession as TradeSession].label }] : []),
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
function snapshotBars() {
  const bars = new Map(props.bars.map(bar => [bar.timestamp, bar]));
  const current = liveBar();
  if (current) bars.set(current.timestamp, current);
  return [...bars.values()].sort((a, b) => a.timestamp - b.timestamp);
}

function updateLiveSnapshot() {
  if (!chart || !pushBar) return;
  const previous = chart.getDataList();
  const next = snapshotBars();
  const last = previous.length - 1;
  for (let i = 0; i < previous.length; i++) {
    const before = previous[i]!;
    const after = next[i];
    const same = after && Object.keys(before).length === Object.keys(after).length &&
      Object.keys(before).every(key => before[key] === after[key]);
    if (same) continue;
    if (i === last && after?.timestamp === before.timestamp) {
      pushBar(after);
    } else {
      // A correction before the last candle, an insertion or a deletion needs a full reload.
      chart.resetData();
      return;
    }
  }
  for (const bar of next.slice(last + 1)) pushBar(bar);
}

function candleX(timestamp: number) {
  const point = chart?.convertToPixel({ timestamp }, { paneId: 'candle_pane' });
  return Array.isArray(point) ? undefined : point?.x;
}

function styles() {
  if (!chart) return;
  chart.setStyles(resolvedTheme.value);
  const dark = resolvedTheme.value === 'dark';
  const { up, down, muted } = readMarketCanvasColors(dark);
  const colors = { upColor: up, downColor: down, noChangeColor: muted };
  chart.setStyles({
    candle: { bar: { ...colors, upBorderColor: up, downBorderColor: down,
      noChangeBorderColor: muted, upWickColor: up, downWickColor: down, noChangeWickColor: muted },
    priceMark: { last: colors },
    tooltip: { showRule: 'follow_cross', showType: 'rect',
      legend: { defaultValue: '--', template: candleTooltipLegends } } },
    indicator: { bars: [colors] },
  });
}
function destroy() {
  chart?.getDom('candle_pane', 'main')?.removeEventListener('pointerleave', clearHover);
  clearHover();
  pushBar = undefined;
  if (element.value && chart) dispose(element.value);
  chart = null;
  appliedOverlayIds = [];
  drawnForecastId = undefined;
  followSession = true;
  fittedMinuteForecast = false;
}
function applyPriceRange() {
  if (!chart || (props.referencePrice == null && props.period !== '1m' && props.period !== '1d')) return;
  chart.overrideYAxis({ paneId: 'candle_pane', createRange: ({ defaultRange }) => {
    const reference = props.referencePrice ?? 0;
    const prices = Number.isFinite(reference) && reference > 0 ? [reference] : [];
    if (showForecast.value && futurePrices.value.length && chart) {
      const visible = chart.getVisibleRange();
      const latestIndex = chart.getDataList().length - 1;
      const slots = minuteSlots.value;
      if (slots) {
        for (const bar of minuteProjection.value) {
          const index = latestIndex + (bar.timestamp - slots.base) / MINUTE_MS;
          if (index >= visible.realFrom && index < visible.realTo) prices.push(bar.low, bar.high);
        }
      } else if (visible.to > latestIndex) {
        for (const bar of futurePrices.value) prices.push(bar.low, bar.high);
      }
    }
    if (!prices.length) return defaultRange;
    const low = Math.min(defaultRange.from, ...prices);
    const high = Math.max(defaultRange.to, ...prices);
    const padding = Math.max(high - low, reference * 0.002) * 0.05;
    const from = low - padding, to = high + padding, range = to - from;
    return { from, to, range, realFrom: from, realTo: to, realRange: range,
      displayFrom: from, displayTo: to, displayRange: range };
  } });
}
function applyOverlays() {
  if (!chart) return;
  // Remove only overlays owned by this prop, including groups removed in the new value.
  // User drawings and other chart-owned overlays must survive updates.
  for (const id of appliedOverlayIds) chart.removeOverlay({ id });
  appliedOverlayIds = [];
  if (props.overlays?.length) {
    const created = chart.createOverlay(props.overlays.map(withHover));
    appliedOverlayIds = (Array.isArray(created) ? created : [created]).filter((id): id is string => id != null);
  }
}
function fitDailyForecast() {
  if (!chart || props.period !== '1d') return;
  if (showForecast.value && dailyFuture.value.length) {
    chart.setOffsetRightDistance((dailyFuture.value.length + 1) * chart.getBarSpace().bar);
  } else if (drawnForecastId === DAILY_FORECAST_OVERLAY_ID) {
    chart.setOffsetRightDistance(80);
  }
}
function fitMinuteForecast() {
  const slots = minuteSlots.value;
  if (!chart || !followSession) return;
  if ((!showForecast.value || !slots || !future.value.length) && fittedMinuteForecast) {
    chart.setBarSpace(10);
    chart.setOffsetRightDistance(120);
    fittedMinuteForecast = false;
    return;
  }
  if (!slots || !showForecast.value || !future.value.length) return;
  const width = chart.getSize('candle_pane', 'main')?.width;
  const dataCount = chart.getDataList().length;
  if (!width || !dataCount) return;
  const space = Math.min(10, width / (dataCount + slots.targets.length + 2));
  chart.setBarSpace(space);
  chart.setOffsetRightDistance((slots.targets.length + 1) * space);
  fittedMinuteForecast = true;
}
function handOffViewport() {
  if (!restoringViewport) followSession = false;
}
function fitHistoryWindow() {
  if (!chart) return;
  const width = chart.getSize('candle_pane', 'main')?.width;
  const count = chart.getDataList().length;
  if (!width || !count) return;
  followSession = false;
  chart.setBarSpace(Math.min(10, width / (count + 2)));
  chart.setOffsetRightDistance(0);
  chart.scrollToRealTime();
}
function fitSessionOnRequest() {
  followSession = true;
  fitMinuteForecast();
}
function applyForecastOverlay() {
  if (!chart) return;
  if (drawnForecastId) chart.removeOverlay({ id: drawnForecastId });
  const annotation = forecastAnnotation.value;
  drawnForecastId = annotation?.id;
  if (annotation) chart.createOverlay([withHover(annotation)]);
}
function focusOnTimestamp(timestamp: number) {
  if (!chart) return;
  followSession = false;
  chart.scrollToTimestamp(timestamp);
  const width = chart.getSize('candle_pane', 'main')?.width;
  const x = candleX(timestamp);
  if (width && x != null) {
    chart.scrollByDistance(width / 2 - x);
  }
}
const formatMinuteDate: FormatDate = ({ dateTimeFormat, timestamp, template }) => {
  const slots = showForecast.value ? minuteSlots.value : null;
  if (slots && timestamp > slots.base) {
    const target = slots.targets[(timestamp - slots.base) / MINUTE_MS - 1];
    return target ? utils.formatDate(dateTimeFormat, target.timestamp, template) : '';
  }
  return utils.formatDate(dateTimeFormat, timestamp, template);
};
const formatDailyDate: FormatDate = ({ dateTimeFormat, timestamp, template }) => {
  const last = lastDailyTimestamp.value;
  if (dailyForecast.value && last != null && timestamp > last) {
    // The library assigns one calendar day to each future slot. Label the
    // compact forecast slots with their actual exchange session dates.
    const target = dailyFuture.value[(timestamp - last) / DAY_MS - 1];
    return showForecast.value && target ? utils.formatDate(dateTimeFormat, target.timestamp, template) : '';
  }
  return utils.formatDate(dateTimeFormat, timestamp, template);
};
function initialize() {
  destroy();
  if (!element.value) return;
  chart = init(element.value, { timezone: props.timezone ?? 'UTC', locale: 'zh-CN',
    ...(props.period === '1m' && props.timezone ? { formatter: { formatDate: formatMinuteDate },
      layout: { barSpaceLimit: { min: 0.25, max: 50 } } } : {}),
    ...(props.period === '1d' ? { formatter: { formatDate: formatDailyDate } } : {}) });
  if (!chart) return;
  chart.getDom('candle_pane', 'main')?.addEventListener('pointerleave', clearHover);
  styles();
  applyPriceRange();
  if (props.period === '1m') {
    // Leave room for ten forecast steps at the default zoom without fabricating candles.
    chart.setOffsetRightDistance(120);
    chart.subscribeAction('onZoom', handOffViewport);
    chart.subscribeAction('onScroll', handOffViewport);
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
    '1y': { type: 'year', span: 1 }, '1w': { type: 'week', span: 1 }, '1M': { type: 'month', span: 1 },
  } as const;
  chart.setPeriod(periods[props.period]);
  chart.setDataLoader({
    getBars: ({ type, callback }) => {
      if (type !== 'init') { callback([], false); return; }
      const bars = snapshotBars();
      const previous = props.liveSnapshot ? chart?.getDataList() : undefined;
      const right = chart && previous?.length ? chart.getVisibleRange().to - 1 : -1;
      const anchor = previous?.[right];
      const oldX = anchor && candleX(anchor.timestamp);
      const followLatest = previous && right === previous.length - 1;
      callback(bars, false);
      if (anchor && oldX != null && bars.length) {
        // Preserve the rightmost visible candle, or the live edge if it was in view.
        const newX = candleX(followLatest ? bars.at(-1)!.timestamp : anchor.timestamp);
        if (newX != null) {
          restoringViewport = true;
          try { chart?.scrollByDistance(oldX - newX); }
          finally { restoringViewport = false; }
        }
      } else if (props.focusTimestamp != null) {
        focusOnTimestamp(props.focusTimestamp);
      }
      fitMinuteForecast();
    },
    subscribeBar: ({ callback }) => { pushBar = callback; },
    unsubscribeBar: () => { pushBar = undefined; },
  });
  applyOverlays();
  fitDailyForecast();
  applyForecastOverlay();
}
watch(() => props.overlays, applyOverlays);
// Chart and API refreshes can reallocate the same data. Update the overlay only
// when a published forecast or its remaining target minutes actually change.
watch([forecastOverlayKey, showForecast], () => {
  applyPriceRange();
  fitDailyForecast();
  fitMinuteForecast();
  applyForecastOverlay();
});
watch(() => minuteSlots.value?.base, fitMinuteForecast, { flush: 'post' });
watch(resolvedTheme, applyForecastOverlay);
watch([() => props.focusTimestamp, () => props.focusRequest], ([timestamp, request], [, previousRequest]) => {
  // Live snapshots may add or remove a selected marker without a navigation request.
  if (props.liveSnapshot && request === previousRequest) return;
  if (timestamp != null) focusOnTimestamp(timestamp);
  else chart?.scrollToRealTime();
});
watch(() => [props.symbol, props.period, props.sourceKey, props.pricePrecision, props.timezone], initialize);
watch(() => props.referencePrice, applyPriceRange);
watch([() => props.bars, () => props.current], ([bars], [previousBars]) => {
  const bar = liveBar();
  if (bars === previousBars && bar && (!props.liveSnapshot || bar.timestamp >= (chart?.getDataList().at(-1)?.timestamp ?? 0))) {
    pushBar?.(bar);
  } else if (props.liveSnapshot) updateLiveSnapshot();
  else chart?.resetData();
});
watch(resolvedTheme, styles);
onMounted(() => {
  initialize();
  observer = new ResizeObserver(() => { chart?.resize(); fitMinuteForecast(); });
  if (element.value) observer.observe(element.value);
});
onBeforeUnmount(() => { observer?.disconnect(); destroy(); });
</script>

<template>
  <div class="min-w-0">
    <div
      class="relative"
      @wheel.passive="clearHover"
      @pointerdown="clearHover"
      @pointerleave="clearHover"
    >
      <div
        ref="element"
        class="h-80 min-w-0 w-full sm:h-[28rem]"
        role="img"
        :aria-label="`${symbol} ${period} K线，红涨绿跌，${timezone ? '时间为' + timezone : '按交易日期显示'}，可拖动和缩放查看历史`"
      />
      <div
        v-if="hoverHint"
        role="tooltip"
        class="pointer-events-none absolute z-10 w-max max-w-[min(24rem,45%)] rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm"
        :style="hintPosition"
      >
        {{ hoverHint }}
      </div>
    </div>
    <div
      v-if="fullMinuteWindow || (minuteSlots && showForecast && future.length)"
      class="mb-2 flex justify-end"
    >
      <Button
        v-if="fullMinuteWindow"
        size="sm"
        variant="ghost"
        @click="fitHistoryWindow"
      >
        查看完整24小时
      </Button>
      <Button
        v-if="minuteSlots && showForecast && future.length"
        size="sm"
        variant="ghost"
        @click="fitSessionOnRequest"
      >
        查看完整分钟图
      </Button>
    </div>
    <KronosForecastPanel
      v-if="dailyForecast || (period === '1m' && forecastResponse?.enabled)"
      v-model:show-forecast="showForecast"
      :period="period === '1d' ? '1d' : '1m'"
      :forecast="dailyForecast ?? forecast"
      :bars="period === '1d' ? dailyFuture : future"
      :accuracy="period === '1d' ? dailyForecast?.accuracy : forecastResponse?.accuracy"
      :timezone="timezone"
      :price-precision="pricePrecision"
    />
  </div>
</template>
