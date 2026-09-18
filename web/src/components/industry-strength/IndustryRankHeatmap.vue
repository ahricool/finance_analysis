<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import type { ECElementEvent } from 'echarts/core';
import { HeatmapChart, CustomChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { IndustryHistory, IndustrySnapshot } from '@/api/industryStrength';
import { selectedDateLeaders } from './display';
import { heatmapOption } from './chartOptions';

use([HeatmapChart, CustomChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

const props = defineProps<{ rows: IndustrySnapshot[]; history: IndustryHistory; selected: string }>();
const emit = defineEmits<{ select: [code: string] }>();
const { resolvedTheme } = useTheme();
const leaders = computed(() => selectedDateLeaders(props.rows));
const option = computed(() => heatmapOption(props.rows, props.history, props.selected, resolvedTheme.value === 'dark' ? 'dark' : 'light'));
const height = computed(() => Math.max(280, leaders.value.length * 32 + 120));
const selectedInSample = computed(() => leaders.value.some((row) => row.industryCode === props.selected));

function select(event: ECElementEvent) {
  const data = event.data;
  if (data && typeof data === 'object' && 'code' in data && typeof data.code === 'string') emit('select', data.code);
}
</script>

<template>
  <div data-testid="industry-heatmap">
    <p class="text-sm text-muted-foreground">
      颜色表示按当日有效行业数归一化的排名位置，不是涨跌幅。样本固定为所选日综合强度前 20 名，不是每天各自的 Top20。
      当前展示已积累的 {{ history.dates.length }} 个快照交易日（接口最多返回 20 个）。
    </p>
    <p
      v-if="selected && !selectedInSample"
      class="mt-2 text-sm text-muted-foreground"
    >
      当前选中行业不在所选日 Top20 中，热力图不扩大样本。
    </p>
    <div
      v-if="history.dates.length && leaders.length"
      class="mt-3 w-full"
      :style="{ height: `${height}px` }"
      aria-label="行业排名热力图"
    >
      <VChart
        :option="option"
        autoresize
        @click="select"
      />
    </div>
    <p
      v-else
      class="py-16 text-center text-muted-foreground"
      data-testid="industry-heatmap-empty"
    >
      暂无排名历史。首次运行后会逐日积累快照，不会用空白日期填充。
    </p>
  </div>
</template>
