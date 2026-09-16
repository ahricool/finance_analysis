<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import type { ECElementEvent } from 'echarts/core';
import { ScatterChart, HeatmapChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, VisualMapComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { IndustrySnapshot, IndustryHistory } from '@/api/industryStrength';
import { stateColors, stateLabels } from './display';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
use([ScatterChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, MarkLineComponent, CanvasRenderer]);
const props = defineProps<{ rows: IndustrySnapshot[]; history: IndustryHistory; selected: string }>();
const emit = defineEmits<{ select: [code: string] }>();
const { resolvedTheme } = useTheme();
const text = computed(() => resolvedTheme.value === 'dark' ? '#b8bcc5' : '#525866');
const grid = computed(() => resolvedTheme.value === 'dark' ? '#30343b' : '#e5e7eb');
const leaders = computed(() => [...props.rows].sort((a, b) => a.strengthRank - b.strengthRank).slice(0, 20));
const bubble = computed(() => ({
  animation: false, grid: { top: 24, right: 30, bottom: 52, left: 70 },
  tooltip: { trigger: 'item', renderMode: 'richText', confine: true,
    formatter: (p: { data: { name: string; value: number[]; state: keyof typeof stateLabels } }) => `${p.data.name} · ${stateLabels[p.data.state]}\n强度 ${p.data.value[0]?.toFixed(1)}\n加速度 ${p.data.value[1]?.toFixed(2)} 个百分点\n成交额脉冲 ${p.data.value[2]?.toFixed(2)}×` },
  xAxis: { type: 'value', min: 0, max: 100, name: 'Strength Score', nameLocation: 'middle', nameGap: 30, nameTextStyle: { color: text.value }, axisLabel: { color: text.value }, splitLine: { lineStyle: { color: grid.value } } },
  yAxis: { type: 'value', scale: true, name: 'Acceleration (百分点)', nameTextStyle: { color: text.value }, axisLabel: { color: text.value }, splitLine: { lineStyle: { color: grid.value } } },
  series: [{ type: 'scatter', symbolSize: (v: number[]) => Math.max(9, Math.min(40, 18 * Math.sqrt(v[2] ?? 0))),
    data: props.rows.map(r => ({ name: r.industryName, code: r.industryCode, state: r.state, value: [r.strengthScore, r.momentumAcceleration5D * 100, r.turnoverRatio5D],
      itemStyle: { color: stateColors[r.state], opacity: 0.85, borderWidth: r.industryCode === props.selected ? 3 : 0, borderColor: text.value },
      label: { show: r.strengthRank <= 5 || r.industryCode === props.selected, formatter: r.industryName, position: 'right', color: text.value } })),
    markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: text.value, type: 'dashed' }, data: [{ xAxis: 50 }, { yAxis: 0 }] },
  }],
}));
const heat = computed(() => ({
  animation: false, grid: { top: 12, right: 20, bottom: 68, left: 100 },
  tooltip: { renderMode: 'richText', confine: true, formatter: (p: { data: { value: number[]; rank: number; name: string } }) => `${p.data.name}\n${props.history.dates[p.data.value[0] ?? 0]} · Rank ${p.data.rank}` },
  xAxis: { type: 'category', data: props.history.dates.map(d => d.slice(5)), axisLabel: { color: text.value }, splitArea: { show: true } },
  yAxis: { type: 'category', inverse: true, data: leaders.value.map(r => r.industryName), axisLabel: { color: text.value }, splitArea: { show: true } },
  visualMap: { min: 0, max: 100, orient: 'horizontal', left: 'center', bottom: 0, text: ['强', '弱'], textStyle: { color: text.value }, inRange: { color: ['#16866d', '#edf0f2', '#e5484d'] } },
  series: [{ type: 'heatmap', data: props.history.items.flatMap(r => {
    const y = leaders.value.findIndex(v => v.industryCode === r.industryCode);
    const x = props.history.dates.indexOf(r.tradeDate);
    return x < 0 || y < 0 ? [] : [{ code: r.industryCode, name: r.industryName, rank: r.strengthRank,
      value: [x, y, r.quality.rankedCount <= 1 ? 50 : 100 * (r.quality.rankedCount - r.strengthRank) / (r.quality.rankedCount - 1)] }];
  }), itemStyle: { borderWidth: 2, borderColor: resolvedTheme.value === 'dark' ? '#171717' : '#fff' } }],
}));
function select(event: ECElementEvent) { const data = event.data; if (data && typeof data === 'object' && 'code' in data && typeof data.code === 'string') emit('select', data.code); }
</script>
<template>
  <Card>
    <CardHeader><CardTitle>行业强度矩阵</CardTitle><CardDescription>左上：弱中改善 · 右上：强且加速 · 左下：弱且恶化 · 右下：强中降温。气泡大小为成交额脉冲。</CardDescription></CardHeader>
    <CardContent>
      <div class="mb-3 flex gap-5 text-xs">
        <span
          v-for="(label, state) in stateLabels"
          :key="state"
          :style="{ color: stateColors[state] }"
        >● {{ label }}</span>
      </div>
      <div
        class="h-96"
        aria-label="行业强度气泡图"
      >
        <VChart
          :option="bubble"
          autoresize
          @click="select"
        />
      </div>
    </CardContent>
  </Card>
  <Card>
    <CardHeader><CardTitle>近 20 个快照交易日 · Rank 热力图</CardTitle><CardDescription>按所选日期 Top20 展示；空白为未保存的行业快照，颜色按当日行业数量归一化。点击联动行业详情。</CardDescription></CardHeader>
    <CardContent>
      <div
        v-if="history.items.length"
        class="h-[520px]"
        aria-label="行业排名热力图"
      >
        <VChart
          :option="heat"
          autoresize
          @click="select"
        />
      </div><p
        v-else
        class="py-10 text-center text-muted-foreground"
      >
        暂无排名历史
      </p>
    </CardContent>
  </Card>
</template>
