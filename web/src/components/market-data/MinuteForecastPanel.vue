<script setup lang="ts">
import { computed } from 'vue';
import { ChevronDown } from 'lucide-vue-next';
import type { ForecastAccuracy, ForecastBar, MinuteForecast } from '@/api/minuteForecast';

const props = defineProps<{
  forecast: MinuteForecast | null;
  bars: ForecastBar[];
  accuracy?: ForecastAccuracy | null;
  timezone?: string;
  pricePrecision?: number;
}>();
const showForecast = defineModel<boolean>('showForecast', { required: true });

const time = (at: number) => new Date(at).toLocaleTimeString('zh-CN', {
  timeZone: props.timezone ?? 'UTC', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const dateTime = (at: number) => new Date(at).toLocaleString('zh-CN', {
  timeZone: props.timezone ?? 'UTC', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const price = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: props.pricePrecision ?? 3 });
const first = computed(() => props.bars[0]);
const last = computed(() => props.bars.at(-1));
const recent = computed(() => {
  const rows = props.accuracy?.recent?.rows ?? [];
  if (!rows.length) return null;
  return {
    count: rows.length,
    mae: rows.reduce((total, row) => total + row.error, 0) / rows.length,
    baseline: rows.reduce((total, row) => total + row.baselineError, 0) / rows.length,
  };
});
const daily = computed(() => {
  const rows = props.accuracy?.daily ?? [];
  const count = rows.reduce((total, row) => total + row.count, 0);
  if (!count) return null;
  return {
    count,
    mae: rows.reduce((total, row) => total + row.mae * row.count, 0) / count,
    baseline: rows.reduce((total, row) => total + row.baselineMae * row.count, 0) / count,
  };
});
const errorSteps = computed(() => {
  const recentRows = new Map(props.accuracy?.recent?.rows.map(row => [row.step, row]));
  const dayRows = new Map(props.accuracy?.daily.map(row => [row.step, row]));
  const steps = [...new Set([...recentRows.keys(), ...dayRows.keys()])].sort((a, b) => a - b);
  return steps.map(step => ({ step, recent: recentRows.get(step), daily: dayRows.get(step) }));
});
</script>

<template>
  <section
    class="mt-3 overflow-hidden rounded-xl border border-border/75 bg-card text-card-foreground"
    aria-label="分钟线预测"
    data-testid="minute-forecast"
  >
    <header class="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 bg-muted/30 px-3 py-2.5 sm:px-4">
      <div class="flex items-center gap-2.5">
        <span
          class="w-4 border-t-2 border-dashed border-blue-600 dark:border-blue-300"
          aria-hidden="true"
        />
        <h3 class="text-sm font-semibold">
          Kronos{{ forecast?.model ? ` ${forecast.model}` : '' }}
        </h3>
        <span
          v-if="forecast?.closeReplay && bars.length"
          class="rounded-md bg-blue-100 px-1.5 py-0.5 text-[11px] font-medium text-blue-800 dark:bg-blue-950 dark:text-blue-200"
        >收盘试算</span>
      </div>
      <label class="inline-flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
        <input
          v-model="showForecast"
          type="checkbox"
          class="accent-blue-600"
        >
        显示预测线
      </label>
    </header>

    <dl class="grid divide-y divide-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
      <div class="min-w-0 space-y-1 px-3 py-3 sm:px-4">
        <dt class="text-xs font-medium text-muted-foreground">
          最后一根预测收盘价
        </dt>
        <dd
          v-if="first && last && forecast"
          class="space-y-1"
        >
          <strong class="block text-lg font-semibold leading-tight text-blue-700 tabular-nums dark:text-blue-300">{{ price(last.close) }}</strong>
          <span class="block text-xs text-muted-foreground tabular-nums">
            {{ time(first.timestamp) }}–{{ time(last.timestamp) }} · {{ bars.length }} 根
          </span>
          <span class="block text-[11px] text-muted-foreground tabular-nums">
            截至 {{ dateTime(forecast.anchor + 60_000) }} · {{ forecast.lookback }} 根输入
          </span>
        </dd>
        <dd
          v-else
          class="text-sm text-muted-foreground"
        >
          等待最新分钟预测
        </dd>
      </div>

      <div class="min-w-0 space-y-1 px-3 py-3 sm:px-4">
        <dt class="text-xs font-medium text-muted-foreground">
          最近误差
        </dt>
        <dd
          v-if="recent && accuracy?.recent"
          class="space-y-1"
        >
          <strong class="block text-lg font-semibold leading-tight tabular-nums">{{ price(recent.mae) }}</strong>
          <span class="block text-xs text-muted-foreground tabular-nums">
            基线 {{ price(recent.baseline) }} · {{ recent.count }} 个样本
          </span>
          <span class="block text-[11px] text-muted-foreground tabular-nums">
            {{ dateTime(accuracy.recent.issuedAt) }} 发出
          </span>
        </dd>
        <dd
          v-else
          class="text-sm text-muted-foreground"
        >
          暂无已核对预测
        </dd>
      </div>

      <div class="min-w-0 space-y-1 px-3 py-3 sm:px-4">
        <dt class="text-xs font-medium text-muted-foreground">
          今日平均误差
        </dt>
        <dd
          v-if="daily"
          class="space-y-1"
        >
          <strong class="block text-lg font-semibold leading-tight tabular-nums">{{ price(daily.mae) }}</strong>
          <span class="block text-xs text-muted-foreground tabular-nums">
            基线 {{ price(daily.baseline) }} · {{ daily.count.toLocaleString('zh-CN') }} 个样本
          </span>
          <span class="block text-[11px] text-muted-foreground tabular-nums">{{ accuracy?.tradingDate }}</span>
        </dd>
        <dd
          v-else
          class="text-sm text-muted-foreground"
        >
          今日暂无已核对样本
        </dd>
      </div>
    </dl>

    <div
      v-if="bars.length || errorSteps.length"
      class="divide-y divide-border/70 border-t border-border/70"
    >
      <details
        v-if="bars.length"
        class="group"
      >
        <summary class="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-xs font-medium sm:px-4 [&::-webkit-details-marker]:hidden">
          预测 OHLC
          <ChevronDown
            class="size-3.5 text-muted-foreground transition-transform group-open:rotate-180"
            aria-hidden="true"
          />
        </summary>
        <div class="px-3 pb-3 sm:px-4">
          <div class="grid grid-cols-5 gap-x-2 border-b border-border/70 py-1.5 text-right text-[11px] text-muted-foreground">
            <span class="text-left">时间</span><span>开盘</span><span>最高</span><span>最低</span><span>收盘</span>
          </div>
          <ol class="divide-y divide-border/50">
            <li
              v-for="bar in bars"
              :key="bar.timestamp"
              class="grid grid-cols-5 gap-x-2 py-1.5 text-right text-xs tabular-nums"
            >
              <span class="text-left text-muted-foreground">{{ time(bar.timestamp) }}</span>
              <span>{{ price(bar.open) }}</span><span>{{ price(bar.high) }}</span><span>{{ price(bar.low) }}</span>
              <strong class="font-semibold text-blue-700 dark:text-blue-300">{{ price(bar.close) }}</strong>
            </li>
          </ol>
        </div>
      </details>
      <details
        v-if="errorSteps.length"
        class="group"
      >
        <summary class="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-xs font-medium sm:px-4 [&::-webkit-details-marker]:hidden">
          分步误差
          <ChevronDown
            class="size-3.5 text-muted-foreground transition-transform group-open:rotate-180"
            aria-hidden="true"
          />
        </summary>
        <div class="px-3 pb-3 sm:px-4">
          <p class="pb-2 text-xs text-muted-foreground">
            误差按收盘价计算。基线沿用预测起点的收盘价，每个到期步长计一个样本。
          </p>
          <div class="grid grid-cols-[4rem_minmax(0,1fr)_minmax(0,1fr)] gap-x-3 border-b border-border/70 py-1.5 text-right text-[11px] text-muted-foreground">
            <span class="text-left">步长</span><span>最近误差</span><span>今日平均误差</span>
          </div>
          <ol class="divide-y divide-border/50">
            <li
              v-for="row in errorSteps"
              :key="row.step"
              class="grid grid-cols-[4rem_minmax(0,1fr)_minmax(0,1fr)] gap-x-3 py-1.5 text-right text-xs tabular-nums"
            >
              <span class="text-left font-medium">+{{ row.step }} 分钟</span>
              <span v-if="row.recent">
                <strong class="block font-semibold">{{ price(row.recent.error) }}</strong>
                <span class="text-[11px] text-muted-foreground">实际 {{ price(row.recent.close) }} · 基线 {{ price(row.recent.baselineError) }}</span>
              </span>
              <span
                v-else
                class="text-muted-foreground"
              >—</span>
              <span v-if="row.daily">
                <strong class="block font-semibold">{{ price(row.daily.mae) }}</strong>
                <span class="text-[11px] text-muted-foreground">基线 {{ price(row.daily.baselineMae) }} · {{ row.daily.count }} 个样本</span>
              </span>
              <span
                v-else
                class="text-muted-foreground"
              >—</span>
            </li>
          </ol>
        </div>
      </details>
    </div>
  </section>
</template>
