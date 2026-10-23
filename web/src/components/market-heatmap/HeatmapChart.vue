<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { use } from 'echarts/core';
import { TreemapChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import type { HeatmapSnapshot, HeatmapStock } from '@/api/marketHeatmap';
import { useTheme } from '@/composables/useTheme';
import { formatCap, formatChange, heatmapTree } from './display';

use([TreemapChart, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ snapshot: HeatmapSnapshot }>();
const chart = ref<InstanceType<typeof VChart> | null>(null);
const emit = defineEmits<{ select: [stock: HeatmapStock] }>();
const rendered = ref(false);
watch(() => props.snapshot, () => { rendered.value = false; });
const { resolvedTheme } = useTheme();
type Node = { id: string; name: string; stock?: HeatmapStock };
const option = computed(() => {
  const border = resolvedTheme.value === 'dark' ? '#16191e' : '#f4f4f5';
  return {
    animation: false,
    tooltip: { renderMode: 'richText', confine: true,
      formatter: (params: { data: Node }) => {
        const row = params.data.stock;
        return row ? `${row.name}\n${row.code}\n${row.groupName}\n涨跌幅  ${formatChange(row.changePct)}\n总市值  ${formatCap(row.marketCap, props.snapshot.market)}` : params.data.name;
      },
    },
    series: [{ type: 'treemap', name: '市场全景', left: 0, right: 0, top: 0, bottom: 28,
      roam: false, nodeClick: false, squareRatio: 1.2, leafDepth: null,
      data: heatmapTree(props.snapshot.items),
      labelLayout: { hideOverlap: true },
      breadcrumb: { show: true, height: 22, bottom: 0, emptyItemWidth: 36,
        itemStyle: { color: '#333842', textStyle: { color: '#fff' } } },
      label: { show: true, color: '#fff', fontSize: 11, lineHeight: 15, overflow: 'truncate',
        formatter: (params: { data: Node }) => {
          const row = params.data.stock;
          return row ? `${row.name}\n${row.code}\n${formatChange(row.changePct)}` : params.data.name;
        },
      },
      upperLabel: { show: true, height: 22, color: '#fff', fontSize: 12, backgroundColor: '#333842' },
      itemStyle: { borderColor: border, borderWidth: 1, gapWidth: 1 },
      levels: [{ itemStyle: { borderWidth: 0, gapWidth: 4 } },
        { itemStyle: { borderWidth: 2, borderColor: border, gapWidth: 1 }, upperLabel: { show: true } },
        { upperLabel: { show: false } }],
    }],
  };
});
function select(event: { data?: unknown }) {
  const node = event.data as Node | undefined;
  const stock = node?.stock;
  if (stock) emit('select', stock);
  else if (node?.id) chart.value?.dispatchAction({ type: 'treemapRootToNode', seriesIndex: 0, targetNodeId: node.id });
}
function finish() {
  const data = chart.value?.getOption() as { series?: { data?: unknown[] }[] } | undefined;
  if (data?.series?.[0]?.data?.length) rendered.value = true;
}
</script>

<template>
  <VChart
    ref="chart"
    :option="option"
    :data-ready="rendered"
    autoresize
    class="min-w-0"
    aria-label="按行业分组的股票市值热力图"
    @click="select"
    @finished="finish"
  />
</template>
