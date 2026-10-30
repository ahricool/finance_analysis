<script setup lang="ts">
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getMacroSeries, type MacroRange, type MacroMode, type MacroSeriesResult } from '@/api/macro';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import MacroSeriesChart from './MacroSeriesChart.vue';
import { macroAssets, ratioKeys } from './display';
const props = defineProps<{ ratios?: boolean }>();
const range = ref<MacroRange>('60d');
const mode = ref<MacroMode>('normalized');
const result = shallowRef<MacroSeriesResult | null>(null);
const loading = ref(true);
const error = shallowRef<ParsedApiError | null>(null);
let sequence = 0;
async function load() {
  const request = ++sequence;
  error.value = null;
  loading.value = true;
  try {
    const response = await getMacroSeries({ range: range.value, mode: props.ratios ? 'normalized' : mode.value,
      ...(props.ratios ? { series: ratioKeys } : { symbols: [...macroAssets], ...(mode.value === 'relative' ? { benchmark: 'SPY.US' } : {}) }),
    });
    if (request === sequence) result.value = response;
  } catch (cause) {
    if (request === sequence) error.value = { ...getParsedApiError(cause), title: props.ratios ? '风险偏好图加载失败' : '跨资产走势图加载失败' };
  } finally { if (request === sequence) loading.value = false; }
}
watch([range, mode, () => props.ratios], load, { immediate: true, flush: 'sync' });
onBeforeUnmount(() => { sequence++; });
</script>
<template>
  <Card
    class="min-w-0"
    :data-testid="ratios ? 'macro-ratio-chart' : 'macro-performance-chart'"
  >
    <CardHeader class="gap-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>{{ ratios ? '风险偏好' : '跨资产走势' }}</CardTitle><CardDescription class="mt-1">
            {{ ratios ? 'Risk Appetite' : 'Cross-Asset Performance' }}
          </CardDescription>
        </div>
        <div class="flex flex-wrap gap-2">
          <FieldSelect
            :model-value="range"
            :options="['20d', '60d', '120d', '250d', 'ytd'].map(value => ({ value, label: value.toUpperCase() }))"
            aria-label="图表区间"
            data-testid="macro-range"
            class="w-28"
            trigger-class="h-9"
            @update:model-value="range = $event as MacroRange"
          />
          <FieldSelect
            v-if="!ratios"
            :model-value="mode"
            :options="[{ value: 'normalized', label: '归一化' }, { value: 'price', label: '价格' }, { value: 'relative', label: '相对 SPY' }]"
            aria-label="图表模式"
            data-testid="macro-mode"
            class="w-32"
            trigger-class="h-9"
            @update:model-value="mode = $event as MacroMode"
          />
        </div>
      </div>
    </CardHeader>
    <CardContent class="space-y-3">
      <AppApiErrorAlert
        v-if="error"
        :error="error"
        action-label="重新加载"
        @action="load"
        @dismiss="error = null"
      />
      <MacroSeriesChart
        v-else
        :result="result"
        :loading="loading"
        :label="ratios ? '风险偏好 Ratio 走势' : '跨资产走势'"
      />
      <p
        v-if="ratios"
        class="text-xs leading-5 text-muted-foreground"
      >
        向上通常代表风险偏好增强，向下代表风险偏好转弱。HYG/LQD 观察信用；IWM/SPY 观察小盘与市场宽度；SMH/SPY 观察半导体领导力；XLY/XLP 观察周期与防御的相对表现。
      </p>
      <p class="text-xs text-muted-foreground">
        {{ ratios || mode !== 'price' ? '各曲线从自身首个有效点归一至 100；起点日期可能不同。' : '价格模式：ETF 为美元价格，VIX 为波动率指数点数。' }} 数据日期：{{ result?.tradeDate ?? '—' }} · 点击图例隐藏 / 显示 · 虚线连接缺失交易日两侧的真实数据，不代表期间实际价格
      </p>
    </CardContent>
  </Card>
</template>
