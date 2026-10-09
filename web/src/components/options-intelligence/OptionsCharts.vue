<script setup lang="ts">
import OptionHelp from './OptionHelp.vue';
import { computed } from 'vue';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import type { OptionMetrics } from '@/api/optionsIntelligence';
import { useTheme } from '@/composables/useTheme';
use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);
const props = defineProps<{ latest: OptionMetrics; history: OptionMetrics[] }>();
const { resolvedTheme } = useTheme();
const textColor = computed(() => resolvedTheme.value === 'dark' ? '#a3a3a3' : '#525252');
const common = computed(() => ({ backgroundColor: 'transparent', textStyle: { color: textColor.value },
  grid: { left: 55, right: 20, top: 35, bottom: 40 }, tooltip: { trigger: 'axis' },
  yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } } }));
const term = computed(() => ({ ...common.value,
  xAxis: { type: 'category', data: props.latest.termStructure?.map(t => `${t.dte}D`) },
  series: [{ name: 'ATM IV', type: 'line', connectNulls: false,
    data: props.latest.termStructure?.map(t => t.atmIv == null ? null : +(t.atmIv * 100).toFixed(2)), itemStyle: { color: '#d97706' } }],
}));
const skew = computed(() => ({ ...common.value,
  xAxis: { type: 'category', data: props.history.map(h => h.tradeDate) },
  series: [{ name: '实际近30D 25Δ Skew', type: 'line', connectNulls: false,
    data: props.history.map(h => h.skew30D == null ? null : +(h.skew30D * 100).toFixed(2)), itemStyle: { color: '#dc2626' } }],
}));
</script>
<template>
  <div class="grid gap-4 md:grid-cols-2">
    <section class="min-w-0 rounded-xl border p-3">
      <h4 class="text-sm">
        <OptionHelp
          label="IV 期限结构"
          compact
        />
      </h4><div
        class="relative h-56 w-full min-w-0 overflow-hidden"
        data-testid="options-chart-frame"
      >
        <VChart
          class="absolute inset-0 h-full w-full"
          :option="term"
          autoresize
        />
      </div>
    </section>
    <section class="min-w-0 rounded-xl border p-3">
      <h4 class="text-sm">
        <OptionHelp
          label="25Δ Skew 日度历史"
          compact
        />
      </h4><div
        class="relative h-56 w-full min-w-0 overflow-hidden"
        data-testid="options-chart-frame"
      >
        <VChart
          v-if="history.some(h => h.skew30D != null)"
          class="absolute inset-0 h-full w-full"
          :option="skew"
          autoresize
        /><p
          v-else
          class="py-20 text-center text-sm text-muted-foreground"
        >
          N/A · 有效日度 Skew 历史不足
        </p>
      </div>
    </section>
  </div>
</template>
