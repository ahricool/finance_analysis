<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import type { ECElementEvent } from 'echarts/core';
import { LineChart, SankeyChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { FlowOverview } from '@/api/dragonTigerFlow';
import { type FlowStock, money, signedStocks } from './display';
use([LineChart, SankeyChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);
const props = defineProps<{ data: FlowOverview; selected: string; stocks?: FlowStock[]; mode: 'trajectory' | 'paths' }>();
const emit = defineEmits<{ select: [id: string]; stock: [symbol: string] }>();
const { resolvedTheme } = useTheme();
const text = computed(() => resolvedTheme.value === 'dark' ? '#d4d4d8' : '#52525b');
const colors = ['#ef4444', '#f97316', '#db2777', '#b91c1c', '#be123c', '#059669', '#16a34a', '#0d9488', '#15803d', '#047857'];
const shown = computed(() => {
  const rows = props.data.concepts;
  const chosen = [...rows.filter(c => (c.netValue ?? 0) > 0).slice(0, 5),
    ...rows.filter(c => (c.netValue ?? 0) < 0).slice(-5)];
  if (!chosen.length) chosen.push(...rows.slice(0, 10));
  const selected = rows.find(c => c.id === props.selected);
  if (selected && !chosen.some(c => c.id === selected.id)) chosen.push(selected);
  return chosen;
});
const option = computed(() => ({
  animation: false, backgroundColor: 'transparent', textStyle: { color: text.value },
  grid: { left: 65, right: 160, top: 30, bottom: 40 },
  tooltip: { trigger: 'axis', confine: true, renderMode: 'richText', valueFormatter: (v: unknown) => money(typeof v === 'number' ? v : null) },
  xAxis: { type: 'category', boundaryGap: false, data: ['起点', ...props.data.dates], axisLabel: { color: text.value } },
  yAxis: { type: 'value', name: '亿元', min: (v: { min: number }) => Math.min(0, v.min),
    max: (v: { max: number }) => Math.max(0, v.max) || 1,
    axisLabel: { color: text.value, formatter: (v: number) => (v / 1e8).toFixed(1) },
    splitLine: { lineStyle: { color: resolvedTheme.value === 'dark' ? '#3f3f46' : '#e4e4e7' } } },
  series: shown.value.map((c, i) => ({
    type: 'line', name: c.name, id: c.id, data: [0, ...c.values], connectNulls: false, symbolSize: 5,
    lineStyle: { width: c.id === props.selected ? 3 : 1.5 }, itemStyle: { color: colors[((c.netValue ?? c.values.filter(v => v !== null).at(-1) ?? 0) < 0 ? 5 : 0) + i % 5] },
    endLabel: { show: true, formatter: `${c.name} ${money(c.netValue)}`, color: text.value, fontSize: 11 },
    labelLayout: { moveOverlap: 'shiftY', hideOverlap: true },
    markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }], label: { show: false } },
  })),
}));
function select(event: ECElementEvent) {
  if (props.mode === 'trajectory') {
    const concept = shown.value.find(c => c.name === event.seriesName);
    if (concept) emit('select', concept.id);
  } else if (event.data && typeof event.data === 'object' && 'symbol' in event.data && typeof event.data.symbol === 'string' && event.data.symbol) emit('stock', event.data.symbol);
}
function pathOption(positive: boolean) {
  const rows = signedStocks(props.stocks ?? [], positive);
  const name = props.data.concepts.find(c => c.id === props.selected)?.name ?? '所选概念';
  const root = 'concept-root';
  return { animation: false, tooltip: { trigger: 'item', renderMode: 'richText', confine: true,
    formatter: (p: { data: { label?: string; signed?: number }; name: string }) => `${p.data.label ?? p.name}\n${money(p.data.signed)}` },
    series: [{ type: 'sankey', left: 5, right: 155, top: 15, bottom: 15, nodeWidth: 10, nodeGap: 16, draggable: false,
      emphasis: { focus: 'adjacency' },
      label: { color: text.value, width: 145, overflow: 'truncate', fontSize: 11, formatter: (p: { data: { label: string } }) => p.data.label },
      itemStyle: { color: positive ? '#ef4444' : '#059669' }, lineStyle: { color: 'source', opacity: 0.35 },
      data: [{ name: root, label: name, signed: rows.reduce((s, r) => s + r.value, 0) },
        ...rows.map((r, i) => ({ name: `stock-${i}`, label: `${r.name} ${money(r.value)}`, symbol: r.symbol, signed: r.value }))],
      links: rows.map((r, i) => ({ source: root, target: `stock-${i}`, value: Math.abs(r.value), signed: r.value, label: `${name} → ${r.name}`, symbol: r.symbol })),
    }] };
}
</script>

<template>
  <div
    v-if="mode === 'trajectory'"
    class="h-[30rem]"
    data-testid="flow-trajectory"
  >
    <VChart
      :option="option"
      autoresize
      @click="select"
    />
  </div>
  <div
    v-else
    class="grid grid-cols-2 gap-4"
    data-testid="flow-paths"
  >
    <div
      v-for="positive in [true, false]"
      :key="String(positive)"
      class="min-w-0"
    >
      <p class="text-sm font-medium">
        {{ positive ? '正贡献' : '负贡献' }} · Top5与其余股票
      </p>
      <div
        v-if="signedStocks(stocks ?? [], positive).length"
        class="h-64"
      >
        <VChart
          :option="pathOption(positive)"
          autoresize
          @click="select"
        />
      </div>
      <p
        v-else
        class="py-20 text-center text-sm text-muted-foreground"
      >
        暂无{{ positive ? '正' : '负' }}贡献
      </p>
    </div>
  </div>
</template>
