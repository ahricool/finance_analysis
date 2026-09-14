<script setup lang="ts">
import { computed } from 'vue';
import type { MacroDataQuality, MacroRatio } from '@/api/macro';
import { formatPercent } from '@/utils/quant';
import { seriesLabel } from './display';
const props = defineProps<{ quality: MacroDataQuality; ratios?: MacroRatio[] }>();
const partialRatios = computed(() => (props.ratios ?? []).filter(item => item.partial));
</script>
<template>
  <details
    v-if="quality.partial"
    class="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm"
    data-testid="macro-quality"
  >
    <summary class="cursor-pointer font-medium">
      宏观数据不完整：{{ quality.available }} / {{ quality.expected }} 个资产数据有效 · 覆盖率 {{ formatPercent(quality.coverage, 0) }}
    </summary>
    <div class="mt-2 space-y-1 text-muted-foreground">
      <p>缺失：{{ quality.missingSymbols.join('、') || '无' }}</p>
      <p>过期：{{ quality.staleSymbols.join('、') || '无' }}</p>
      <p>历史不足：{{ quality.insufficientHistorySymbols.join('、') || '无' }}</p>
      <p>Ratio 数据不完整：{{ partialRatios.map(item => seriesLabel(item.key)).join('、') || '无' }}</p>
      <p>有效资产数反映数据新鲜度；历史不足仍可能导致信号不可用。</p>
    </div>
  </details>
</template>
