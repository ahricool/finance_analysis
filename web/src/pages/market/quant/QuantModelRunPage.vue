<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { ModelRun } from '@/types/quant';
import {
  formatScore,
  MODEL_TARGET_COPY,
  PRODUCTION_PREDICTION_HORIZON,
  isTrainableModelKey,
  scalarMetrics,
} from '@/utils/quant';
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/authStore';
import { useQuantMarket } from '@/composables/useQuantMarket';
const route = useRoute();
const { market, marketQuery } = useQuantMarket();
const auth = useAuthStore();
const item = ref<ModelRun | null>(null);
const error = ref<ParsedApiError | null>(null);
const reason = ref('验证指标与风险检查已人工确认');
const isAdmin = computed(() => auth.currentUser?.role === 'admin');
const targetCopy = computed(() =>
  item.value && isTrainableModelKey(item.value.modelKey)
    ? MODEL_TARGET_COPY[item.value.modelKey]
    : null,
);
const metricRows = computed(() => scalarMetrics(item.value?.metrics));
const storedHorizon = computed(() => {
  const raw = item.value?.targetConfig?.predictionHorizon ?? item.value?.splitConfig?.predictionHorizon;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
});
const legacyHorizon = computed(() =>
  storedHorizon.value != null && storedHorizon.value !== PRODUCTION_PREDICTION_HORIZON
    ? storedHorizon.value
    : null,
);
let requestVersion = 0;
watch(
  [market, () => route.params.runId],
  async ([current, runId]) => {
    const version = ++requestVersion;
    item.value = null;
    error.value = null;
    try {
      const value = await quantApi.model(Number(runId), current);
      if (version === requestVersion) item.value = value;
    } catch (err) {
      if (version === requestVersion) error.value = getParsedApiError(err);
    }
  },
  { immediate: true },
);
async function publish() {
  if (
    !item.value ||
    !window.confirm('确认将此候选模型发布为 production？当前 production 将被退役。')
  )
    return;
  try {
    item.value = await quantApi.publish(item.value.id, reason.value, market.value);
  } catch (err) {
    error.value = getParsedApiError(err);
  }
}
</script>
<template>
  <div class="space-y-4">
    <RouterLink
      :to="{ path: '/research/quant/models', query: marketQuery() }"
      class="text-sm font-medium underline-offset-4 hover:underline"
    >
      ← 返回模型列表
    </RouterLink><ApiErrorAlert
      v-if="error"
      :error="error"
    /><template v-if="item">
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-semibold">
            {{ targetCopy?.shortName ?? item.modelKey }}
          </h2>
          <p class="text-xs text-muted-foreground">
            {{ item.modelVersion }} · {{ item.status }}
          </p>
        </div>
        <Button
          v-if="isAdmin && item.status === 'candidate'"
          @click="publish"
        >
          发布为 production
        </Button>
      </header>
      <input
        v-if="isAdmin && item.status === 'candidate'"
        v-model="reason"
        class="w-full rounded-xl border border-border bg-background p-2 text-sm"
        aria-label="发布原因"
      />
      <section class="grid gap-3 md:grid-cols-3">
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-foreground">
            训练方式
          </p>
          <p>Walk-forward</p>
        </div>
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-foreground">
            预测目标
          </p>
          <p>{{ targetCopy?.target ?? '—' }}</p>
        </div>
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-foreground">
            预测周期
          </p>
          <p>{{ PRODUCTION_PREDICTION_HORIZON }} 个交易日</p>
          <p
            v-if="legacyHorizon != null"
            class="mt-1 text-xs text-muted-foreground"
          >
            历史记录为 {{ legacyHorizon }} 个交易日，不能用于当前 production
          </p>
        </div>
      </section>
      <p
        v-if="targetCopy"
        class="text-xs text-muted-foreground"
      >
        {{ targetCopy.detail }}
      </p>
      <section class="rounded-xl border bg-card p-4">
        <h3 class="text-sm font-semibold">
          评价指标
        </h3>
        <div class="mt-3 grid gap-2 sm:grid-cols-3">
          <div
            v-for="[key, value] in metricRows"
            :key="key"
            class="rounded-lg bg-background p-2"
          >
            <p class="text-xs text-muted-foreground">
              {{ key }}
            </p>
            <p>{{ formatScore(value) }}</p>
          </div>
        </div>
      </section>
      <div
        v-if="item.warnings.length"
        class="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning"
      >
        {{ item.warnings.join('；') }}
      </div>
      <div
        v-if="item.error"
        class="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
      >
        {{ item.error }}
      </div>
    </template>
  </div>
</template>
