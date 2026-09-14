<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getMacroSeries, type MacroRange, type MacroMode, type MacroSeriesResult } from '@/api/macro';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import MacroSeriesChart from './MacroSeriesChart.vue';
import { defaultAssets, macroAssets, ratioKeys, seriesLabel } from './display';
const props = defineProps<{ ratios?: boolean }>();
const range = ref<MacroRange>('60d');
const mode = ref<MacroMode>('normalized');
const symbols = ref([...defaultAssets]);
const result = shallowRef<MacroSeriesResult | null>(null);
const loading = ref(true);
const error = shallowRef<ParsedApiError | null>(null);
let sequence = 0;
function toggleAsset(code: string) {
  if (symbols.value.includes(code)) symbols.value = symbols.value.filter(s => s !== code);
  else if (symbols.value.length < 8) symbols.value = [...symbols.value, code];
}
async function load() {
  const request = ++sequence;
  error.value = null;
  if (!props.ratios && !symbols.value.length) { result.value = null; loading.value = false; return; }
  loading.value = true;
  try {
    const response = await getMacroSeries({ range: range.value, mode: props.ratios ? 'normalized' : mode.value,
      ...(props.ratios ? { series: ratioKeys } : { symbols: [...symbols.value], ...(mode.value === 'relative' ? { benchmark: 'SPY.US' } : {}) }),
    });
    if (request === sequence) result.value = response;
  } catch (cause) {
    if (request === sequence) error.value = { ...getParsedApiError(cause), title: props.ratios ? '风险偏好图加载失败' : '跨资产走势图加载失败' };
  } finally { if (request === sequence) loading.value = false; }
}
watch([range, mode, symbols], load, { immediate: true, flush: 'sync' });
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
          <NativeSelect
            v-model="range"
            aria-label="图表区间"
            data-testid="macro-range"
          >
            <NativeSelectOption
              v-for="r in (['20d', '60d', '120d', '250d', 'ytd'] as const)"
              :key="r"
              :value="r"
            >
              {{ r.toUpperCase() }}
            </NativeSelectOption>
          </NativeSelect>
          <NativeSelect
            v-if="!ratios"
            v-model="mode"
            aria-label="图表模式"
            data-testid="macro-mode"
          >
            <NativeSelectOption value="normalized">
              归一化
            </NativeSelectOption><NativeSelectOption value="price">
              价格
            </NativeSelectOption><NativeSelectOption value="relative">
              相对 SPY
            </NativeSelectOption>
          </NativeSelect>
        </div>
      </div>
      <div
        v-if="!ratios"
        class="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="选择资产，最多 8 个"
      >
        <Button
          v-for="code in macroAssets"
          :key="code"
          size="sm"
          :variant="symbols.includes(code) ? 'secondary' : 'ghost'"
          :aria-pressed="symbols.includes(code)"
          :disabled="!symbols.includes(code) && symbols.length >= 8"
          :data-testid="`macro-asset-${code}`"
          @click="toggleAsset(code)"
        >
          {{ seriesLabel(code) }}
        </Button>
        <span class="ml-2 text-xs text-muted-foreground">{{ symbols.length }} / 8</span>
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
        {{ ratios || mode !== 'price' ? '各曲线从自身首个有效点归一至 100；起点日期可能不同。' : '价格模式：ETF 为美元价格，VIX 为波动率指数点数。' }} 数据日期：{{ result?.tradeDate ?? '—' }} · 点击图例隐藏 / 显示
      </p>
    </CardContent>
  </Card>
</template>
