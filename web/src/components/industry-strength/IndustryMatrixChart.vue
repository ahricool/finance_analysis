<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import type { ECElementEvent } from 'echarts/core';
import { ScatterChart } from 'echarts/charts';
import { GraphicComponent, GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { IndustrySnapshot } from '@/api/industryStrength';
import { bubbleSize, stateBadgeClass, stateLabels } from './display';
import { bubbleLegendSamples, matrixOption } from './chartOptions';

use([ScatterChart, GridComponent, TooltipComponent, MarkLineComponent, GraphicComponent, CanvasRenderer]);

const props = defineProps<{ rows: IndustrySnapshot[]; selected: string }>();
const emit = defineEmits<{ select: [code: string] }>();
const { resolvedTheme } = useTheme();
const option = computed(() => matrixOption(props.rows, props.selected, resolvedTheme.value === 'dark' ? 'dark' : 'light'));

function select(event: ECElementEvent) {
  const data = event.data;
  if (data && typeof data === 'object' && 'code' in data && typeof data.code === 'string') emit('select', data.code);
}
</script>

<template>
  <div data-testid="industry-matrix">
    <div class="mb-3 flex flex-wrap gap-x-4 gap-y-2 text-xs">
      <span
        v-for="(label, state) in stateLabels"
        :key="state"
        class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"
        :class="stateBadgeClass[state]"
      >{{ label }}</span>
    </div>
    <div
      class="h-[28rem] min-h-80 w-full"
      aria-label="行业强度气泡图"
    >
      <VChart
        :option="option"
        autoresize
        @click="select"
      />
    </div>
    <div
      class="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted-foreground"
      data-testid="industry-bubble-legend"
    >
      <span>气泡大小 = 成交额脉冲，不是市值、绝对成交额或资金净流入</span>
      <span
        v-for="sample in bubbleLegendSamples"
        :key="sample"
        class="inline-flex items-center gap-2"
      >
        <span
          class="inline-block rounded-full border border-foreground/40 bg-foreground/20"
          :style="{ width: `${bubbleSize(sample)}px`, height: `${bubbleSize(sample)}px` }"
        />
        {{ sample }}×
      </span>
    </div>
    <p class="mt-2 text-xs leading-6 text-muted-foreground">
      四象限辅助线（综合强度 50、动量变化 0）不是买卖阈值，与五种状态不是一一对应。
    </p>
  </div>
</template>
