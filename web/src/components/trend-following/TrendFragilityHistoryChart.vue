<script setup lang="ts">
import { computed } from 'vue';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { use, type ComposeOption } from 'echarts/core';
import type { LineSeriesOption } from 'echarts/charts';
import type { GridComponentOption, TooltipComponentOption } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { TrendSnapshot } from '@/types/trendFollowing';

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent]);

const props = defineProps<{ history: Pick<TrendSnapshot, 'tradeDate' | 'fragilityScore'>[] }>();
const { resolvedTheme } = useTheme();
const ordered = computed(() => [...props.history].sort((a, b) => a.tradeDate.localeCompare(b.tradeDate)));
const ranks = computed(() => ordered.value.map(row => row.fragilityScore ?? null));
const hasRanks = computed(() => ranks.value.some(rank => rank !== null));
const option = computed<ComposeOption<LineSeriesOption | GridComponentOption | TooltipComponentOption>>(() => {
  const dark = resolvedTheme.value === 'dark';
  const muted = dark ? '#a3a3a3' : '#525252';
  const split = dark ? 'rgba(255,255,255,.12)' : 'rgba(0,0,0,.08)';
  return {
    animation: false,
    tooltip: {
      trigger: 'axis', confine: true,
      backgroundColor: dark ? '#262626' : '#ffffff',
      borderColor: split,
      textStyle: { color: dark ? '#fafafa' : '#171717' },
      valueFormatter: value => value == null ? '数据不足' : `${value} / 100`,
    },
    grid: { left: 12, right: 16, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: ordered.value.map(row => row.tradeDate),
      axisLabel: { color: muted, hideOverlap: true, fontSize: 11, formatter: (value: string) => value.slice(5) },
      axisLine: { lineStyle: { color: split } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', min: 0, minInterval: 1,
      max: 100,
      axisLabel: { color: muted, formatter: '{value}' },
      splitLine: { lineStyle: { color: split } },
    },
    series: [{
      name: 'Fragility', type: 'line', smooth: false, connectNulls: false,
      showSymbol: true, symbolSize: 6,
      itemStyle: { color: dark ? '#60a5fa' : '#2563eb' },
      lineStyle: { width: 2 },
      data: ranks.value,
    }],
  };
});
</script>

<template>
  <section
    class="min-w-0 rounded-lg border p-3 sm:p-4"
    aria-label="趋势脆弱性历史"
    data-testid="trend-fragility-history"
  >
    <h3 class="font-semibold">
      趋势脆弱性走势
    </h3>
    <p class="mt-1 text-xs text-muted-foreground">
      Fragility · 截至所选交易日最近 {{ history.length }} 个快照 · 分数越高越脆弱
    </p>
    <div
      v-if="hasRanks"
      class="mt-3 h-40 min-w-0"
    >
      <VChart
        :option="option"
        autoresize
        role="img"
        aria-label="Fragility 历史折线图，横轴为交易日，纵轴为脆弱性，越高越脆弱；缺失数据保留断点。"
      />
    </div>
    <p
      v-else
      class="py-12 text-center text-sm text-muted-foreground"
    >
      暂无脆弱性历史
    </p>
  </section>
</template>
