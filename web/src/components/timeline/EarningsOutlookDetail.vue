<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { timelineApi, type EarningsDetail } from '@/api/timeline';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/stores/authStore';
import EarningsOutlookSummary from './EarningsOutlookSummary.vue';
import { searchStatus, guidanceLabels, scenarioLabels, price } from './earningsFormat';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
const props = defineProps<{ eventId: number }>();
const auth = useAuthStore();
const data = ref<EarningsDetail | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const taskId = ref('');
const selected = ref(0);
let generation = 0;
async function load() {
  const id = ++generation;
  loading.value = true;
  error.value = null;
  try { const result = await timelineApi.earningsDetail(props.eventId); if (id === generation) data.value = result; }
  catch (err) { if (id === generation) error.value = getParsedApiError(err); }
  finally { if (id === generation) loading.value = false; }
}
watch(() => props.eventId, () => { data.value = null; selected.value = 0; taskId.value = ''; void load(); }, { immediate: true });
const version = computed(() => data.value?.versions[selected.value]);
const prediction = computed(() => version.value?.prediction);
async function refresh() {
  loading.value = true;
  try { taskId.value = (await timelineApi.refreshEarnings(props.eventId)).taskId; }
  catch (err) { error.value = getParsedApiError(err); }
  finally { loading.value = false; }
}
function safeUrl(value: string) { return /^https?:\/\//i.test(value) ? value : undefined; }
function when(value: string | null | undefined) { return value ? formatDateTimeInDisplayTimezone(value) : '日期未知'; }
</script>
<template>
  <section
    class="space-y-4 border-t border-border pt-4"
    data-testid="earnings-outlook-detail"
  >
    <h3 class="font-semibold">
      财报前瞻与首日预测
    </h3>
    <ApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p
      v-if="loading"
      role="status"
      class="text-sm text-muted-foreground"
    >
      正在加载…
    </p>
    <EarningsOutlookSummary
      v-if="data?.summary"
      :outlook="data.summary"
    />
    <p
      v-else-if="!loading"
      class="text-sm text-muted-foreground"
    >
      暂无前瞻数据，原财报信息仍可查看。
    </p>
    <div
      v-if="auth.currentUser?.role === 'admin'"
      class="space-y-1"
    >
      <Button
        variant="outline"
        size="sm"
        :disabled="loading || !!taskId"
        @click="refresh"
      >
        异步刷新前瞻
      </Button>
      <p
        v-if="taskId"
        class="text-xs text-muted-foreground"
      >
        任务已提交，可在任务中心查看。{{ taskId }}
      </p>
    </div>
    <template v-if="version && prediction">
      <label class="block text-sm">预测版本
        <select
          v-model="selected"
          class="mt-1 w-full rounded-md border border-input bg-background p-2"
        >
          <option
            v-for="(v, i) in data?.versions"
            :key="v.id"
            :value="i"
          >{{ when(v.generatedAt) }} · {{ v.stage }} · {{ v.applicability }}</option>
        </select>
      </label>
      <div class="space-y-2 text-sm">
        <p>{{ prediction.conclusion }}</p>
        <p>财报判断 {{ prediction.earningsConfidence }}/10：{{ prediction.earningsConfidenceReason }}</p>
        <p>{{ prediction.earningsReason }}</p>
        <p>指引：{{ guidanceLabels[prediction.guidance || 'unknown'] }}</p>
        <p>首日走势 {{ prediction.reactionConfidence }}/10：{{ prediction.reactionConfidenceReason }}</p>
        <p>{{ prediction.reactionReason }}</p>
        <p class="text-xs text-muted-foreground">
          模型证据评分，非胜率；价格范围不保证覆盖盘中波动。
        </p>
        <p v-if="prediction.assumption">
          {{ prediction.assumption }}
        </p>
      </div>
      <div class="space-y-1 rounded-lg border border-border p-3 text-sm">
        <h4 class="font-medium">
          所选版本的首日预测
        </h4>
        <p>{{ prediction.targetTradingDate }} · 预计收盘 {{ price(prediction.expectedClose) }} · 涨跌 {{ prediction.expectedReturnPct?.toFixed(2) ?? '—' }}%</p>
        <p>盘中 {{ price(prediction.intradayLow) }} – {{ price(prediction.intradayHigh) }}</p>
        <p class="text-xs text-muted-foreground">
          参考 {{ price(prediction.referencePrice) }} · {{ when(prediction.referencePriceAt) }} · {{ prediction.referencePriceSession }}
        </p>
      </div>
      <div class="space-y-2 text-sm">
        <h4 class="font-medium">
          一致预期及比较口径
        </h4>
        <p
          v-for="metric in (['eps', 'revenue'] as const)"
          :key="metric"
        >
          {{ metric === 'eps' ? 'EPS' : '营收' }}：{{ prediction[metric]?.judgment }} · 预测值 {{ prediction[metric]?.expectedValue ?? '—' }}
          <template v-if="prediction[metric]?.consensus">
            / 预期 {{ prediction[metric]?.consensus?.value }} {{ prediction[metric]?.consensus?.currency }} {{ prediction[metric]?.consensus?.unit }}
            · {{ prediction[metric]?.consensus?.quarter }} · {{ prediction[metric]?.consensus?.basis || '口径未知' }}
            · {{ prediction[metric]?.consensus?.source }} · {{ when(prediction[metric]?.consensus?.asOf) }}
          </template>
        </p>
        <p
          v-if="prediction.tolerance"
          class="text-xs text-muted-foreground"
        >
          Meet：EPS ±max(|预期|×{{ prediction.tolerance.epsRelativeTolerance * 100 }}%, {{ prediction.tolerance.epsAbsoluteUsd }} USD)，营收 ±{{ prediction.tolerance.revenueRelativeTolerance * 100 }}%。负 EPS 也以绝对值计算容差，数值更高为更好。
        </p>
      </div>
      <div class="grid gap-3 sm:grid-cols-3">
        <div
          v-for="scenario in prediction.scenarios"
          :key="scenario.name"
          class="rounded-lg border border-border p-3 text-sm"
        >
          <h4 class="font-medium">
            {{ scenarioLabels[scenario.name] }}
          </h4>
          <p>{{ scenario.conditions }}</p><p>{{ scenario.reactionReason }}</p>
          <p class="mt-2 tabular-nums">
            {{ price(scenario.low) }} – {{ price(scenario.high) }}
          </p>
        </div>
      </div>
      <div class="space-y-2 text-sm">
        <h4 class="font-medium">
          来源与搜索状态
        </h4>
        <p>{{ searchStatus[version.searchEvidence.status] || '搜索执行未能确认' }} · 请求 {{ version.searchEvidence.requested ? '是' : '否' }} · 配置支持 {{ version.searchEvidence.configuredSupport ? '是' : '否' }}</p>
        <p>研究截止 {{ when(version.dataCutoff) }} · 发布前冻结 {{ when(version.releaseCutoff) }}</p>
        <ul class="space-y-2">
          <li
            v-for="source in version.research.sources"
            :key="source.sourceId"
            class="break-words"
          >
            [{{ source.sourceId }}] <a
              :href="safeUrl(source.url)"
              target="_blank"
              rel="noopener noreferrer"
              class="underline"
            >{{ source.title }}</a>
            · {{ source.publisher }} · {{ source.sourceType }}
            <p class="text-xs text-muted-foreground">
              发布 {{ when(source.publishedAt) }} · 检索 {{ when(source.retrievedAt) }}
            </p>
          </li>
        </ul>
        <p
          v-for="(fact, i) in version.research.facts"
          :key="i"
        >
          {{ fact.text }} [{{ fact.sourceIds.join(', ') }}]
        </p>
        <p
          v-for="(conflict, i) in version.research.conflicts"
          :key="i"
        >
          资料冲突：{{ conflict.description }}；采用依据：{{ conflict.reason }} [{{ conflict.sourceIds.join(', ') }}]
        </p>
      </div>
      <div class="text-sm">
        <h4 class="font-medium">
          缺失数据与不确定因素
        </h4>
        <ul class="list-inside list-disc text-muted-foreground">
          <li
            v-for="(text, i) in [...(prediction.missingData || []), ...(prediction.uncertainties || []), ...(version.research.uncertainties || [])]"
            :key="i"
          >
            {{ text }}
          </li>
        </ul>
        <p class="mt-2 text-xs">
          阶段 {{ version.stage }} · {{ version.backend }}/{{ version.model }} · {{ version.promptVersion }}
        </p>
      </div>
      <div
        v-if="data?.actual && data.actual.predictionId === version.id"
        class="space-y-1 rounded-lg bg-muted/50 p-3 text-sm"
      >
        <h4 class="font-medium">
          预测与实际对照 · {{ data.actual.status === 'pending' ? '数据待齐全' : '已完成' }}
        </h4>
        <p>EPS {{ data.actual.actual.eps?.value ?? '—' }}（{{ data.actual.eps }}） · 营收 {{ data.actual.actual.revenue?.value ?? '—' }}（{{ data.actual.revenue }}）</p>
        <p v-if="data.actual.actual.ohlc">
          正常时段 OHLC：{{ price(data.actual.actual.ohlc.open) }} / {{ price(data.actual.actual.ohlc.high) }} / {{ price(data.actual.actual.ohlc.low) }} / {{ price(data.actual.actual.ohlc.close) }}
        </p>
        <p>收盘误差 {{ data.actual.closeError?.toFixed(2) ?? '—' }} · 方向正确 {{ data.actual.directionCorrect == null ? '—' : data.actual.directionCorrect ? '是' : '否' }} · 区间覆盖 {{ data.actual.rangeCovered == null ? '—' : data.actual.rangeCovered ? '是' : '否' }}</p>
        <p class="text-xs text-muted-foreground">
          {{ data.actual.actual.missingReason }}
        </p>
      </div>
    </template>
  </section>
</template>
