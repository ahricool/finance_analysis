<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { optionsIntelligenceApi, type OptionsDetail, type OptionsView } from '@/api/optionsIntelligence';
import { tasksApi } from '@/api/tasks';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import OptionsScores from './OptionsScores.vue';
import OptionsDataControls from './OptionsDataControls.vue';
import OptionHelp from './OptionHelp.vue';
import OptionsCharts from './OptionsCharts.vue';
import { eventLabels, formatOptionNumber as num, formatOptionPct as pct, reasonLabel } from './labels';

const props = defineProps<{ symbol: string; initialView?: OptionsView; initialDate?: string }>();
const mode = ref<OptionsView>(props.initialView ?? 'official'), requestedDate = ref(props.initialDate ?? '');
const visibleDate = computed(() => data.value?.tradeDate ?? requestedDate.value);
const dates = computed(() => data.value?.availableDates ?? []);
const data = ref<OptionsDetail | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false), working = ref(false), taskId = ref('');
const expiry = ref(''), kind = ref('all'), source = ref('yfinance');
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

const latest = computed(() => data.value?.latest);
const expirations = computed(() => [...new Set(latest.value?.contracts?.map(c => c.expiration))].sort().map(value => ({ value, label: value })));
const sources = computed(() => [...new Set(latest.value?.contracts?.map(c => c.dataSource))].map(value => ({ value, label: value })));
const chain = computed(() => latest.value?.contracts?.filter(c => (!expiry.value || c.expiration === expiry.value) &&
  (kind.value === 'all' || c.optionType === kind.value) && c.dataSource === source.value).sort((a, b) => a.strike - b.strike) ?? []);
const anomalies = computed(() => [...(latest.value?.events ?? [])].sort((a, b) => b.severity - a.severity).slice(0, 30));

const refLabels: Record<string, string> = {
  threshold: '触发阈值',
  percentile: '历史分位 (%)',
  sample_days: '样本天数',
  cohort: '同类分桶',
  estimated: '估算值',
  allowance: '动态容忍度',
  rule: '规则版本',
  change: '变动值',
  previous: '前日 OI',
  oi_date: 'OI 日期',
  previous_oi_date: '前次 OI 日期',
  known_at: '可知时间',
  source: '数据源',
  target_dte: '目标期限 (D)',
  actual_dte: '实际期限 (D)',
  expiration: '到期日',
  value: '观测值',
  feed_type: '报价类型',
};

function formatRefValue(val: unknown): string {
  if (val == null) return 'N/A';
  if (typeof val === 'boolean') return val ? '是' : '否';
  if (typeof val === 'number') return num(val, 3);
  if (Array.isArray(val)) return val.join(' / ');
  if (typeof val === 'object') return JSON.stringify(val);
  return String(val);
}

const coverageSummary = computed(() => {
  const cov = latest.value?.coverage as Record<string, unknown> | undefined;
  if (!cov) return null;
  const retained = cov.retainedBySource as Record<string, Record<string, unknown>> | undefined;
  if (!retained) return null;
  return Object.entries(retained).map(([key, item]) => ({
    source: key,
    retainedCount: item.retainedContractCount ?? item.retained_contract_count,
    eligibleCount: item.eligibleContractCount ?? item.eligible_contract_count,
    truncated: Boolean(item.truncatedContracts ?? item.truncated_contracts),
  }));
});

async function load(version = generation) {
  loading.value = true;
  try {
    const response = await optionsIntelligenceApi.detail(props.symbol, {
      view: mode.value,
      tradeDate: mode.value === 'official' ? requestedDate.value || undefined : undefined,
    });
    if (version !== generation) return;
    data.value = response;
    if (!expirations.value.some(e => e.value === expiry.value)) expiry.value = expirations.value[0]?.value ?? '';
    if (!sources.value.some(s => s.value === source.value)) source.value = sources.value[0]?.value ?? 'yfinance';
  } catch (e) {
    if (version === generation) error.value = getParsedApiError(e);
  } finally {
    if (version === generation) loading.value = false;
  }
}

async function poll(id: string, version: number) {
  try {
    const task = await tasksApi.getTaskRunDetail(id);
    if (version !== generation) return;
    if (['completed', 'partial', 'failed', 'cancelled', 'skipped'].includes(task.status)) {
      working.value = false;
      if (task.status !== 'completed') error.value = getParsedApiError(new Error(task.error || task.message || '任务未完成，请在任务中心查看原因'));
      await load(version);
      return;
    }
    timer = setTimeout(() => { void poll(id, version); }, 3000);
  } catch (e) {
    if (version === generation) {
      working.value = false;
      error.value = getParsedApiError(e);
    }
  }
}

async function refresh(explain = false) {
  const version = generation;
  working.value = true;
  error.value = null;
  try {
    const task = await optionsIntelligenceApi.refresh(props.symbol, explain, {
      view: mode.value,
      tradeDate: visibleDate.value || undefined,
    });
    if (version !== generation) return;
    taskId.value = task.taskId;
    void poll(task.taskId, version);
  } catch (e) {
    if (version === generation) {
      error.value = getParsedApiError(e);
      working.value = false;
    }
  }
}

watch(() => [props.initialView, props.initialDate], () => {
  mode.value = props.initialView ?? 'official';
  requestedDate.value = props.initialDate ?? '';
});

watch(() => [props.symbol, mode.value, requestedDate.value], () => {
  generation++;
  clearTimeout(timer);
  expiry.value = '';
  source.value = 'yfinance';
  data.value = null;
  error.value = null;
  taskId.value = '';
  working.value = false;
  void load();
}, { immediate: true });

onBeforeUnmount(() => {
  generation++;
  clearTimeout(timer);
});
</script>

<template>
  <div
    class="w-full min-w-0 max-w-full space-y-5"
    data-testid="options-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card/70 px-4 py-3">
      <div>
        <h3 class="font-semibold">
          期权情报 <span class="text-xs font-normal text-muted-foreground">Options Intelligence</span>
        </h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          {{ latest?.evidenceGrade ? `证据 ${latest.evidenceGrade} · ${latest.status === 'warming_up' ? '历史预热' : '已采集'}` : '尚未采集' }} · {{ formatDateTimeInDisplayTimezone(latest?.observedAt) }}
          <span
            v-if="latest?.underlyingPrice != null"
            class="ml-2 font-mono text-foreground"
          >标的 ${{ num(latest.underlyingPrice) }}</span>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <LoadingButton
          :loading="working"
          @click="refresh()"
        >
          刷新期权链
        </LoadingButton>
        <Button
          variant="outline"
          :disabled="working || !latest || mode === 'preview'"
          @click="refresh(true)"
        >
          解释异常
        </Button>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-3">
      <OptionsDataControls
        :mode="mode"
        :date="visibleDate"
        :dates="dates"
        @update:mode="mode = $event"
        @update:date="requestedDate = $event"
      />
      <p
        v-if="mode === 'preview'"
        class="text-xs text-muted-foreground"
      >
        盘中预演不写入正式事件表，需切换至「正式收盘」方可使用 LLM 解释异常。
      </p>
    </div>

    <AppApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />

    <p
      v-if="taskId"
      class="rounded-lg border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
    >
      {{ working ? '任务执行中，可离开页面稍后查看' : '任务已结束' }} · <RouterLink
        class="font-mono underline"
        :to="{ path: '/tasks/runs', query: { taskId } }"
      >
        查看任务 {{ taskId }}
      </RouterLink>
    </p>

    <p
      v-if="loading && !data"
      class="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground"
    >
      加载期权数据…
    </p>

    <p
      v-if="data && !latest"
      class="rounded-xl border border-dashed p-6 text-center text-muted-foreground"
    >
      {{ data.reason }}
    </p>

    <template v-if="latest">
      <p
        v-if="latest.refreshStatus === 'failed'"
        class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-600 dark:text-amber-400"
      >
        刷新失败，显示上次预演：{{ latest.refreshReason }}
      </p>

      <OptionsScores :scores="latest.scores" />

      <div class="rounded-xl border bg-muted/20 p-3.5 text-xs text-muted-foreground">
        <p class="text-sm text-foreground/90">
          {{ latest.riskSummary }}
        </p>
        <p
          v-if="mode === 'preview'"
          class="mt-1"
        >
          盘中成交仅用当日绝对规则，不与全天成交比较；IV/Skew参考先前正式收盘样本，可信度较低。
        </p>
      </div>

      <details class="rounded-xl border bg-card/60 p-3.5 text-sm">
        <summary class="cursor-pointer font-medium">
          <OptionHelp
            label="链覆盖与样本限制"
            compact
          /> · 历史 {{ latest.historyDays }} 个可比交易日
          <span
            v-if="latest.volumeHistoryDays != null"
            class="ml-2 text-xs font-normal text-muted-foreground"
          >（同阶段成交量样本 {{ latest.volumeHistoryDays }} 日）</span>
        </summary>
        <div
          v-if="coverageSummary?.length"
          class="mt-2.5 flex flex-wrap gap-2 text-xs"
        >
          <span
            v-for="item in coverageSummary"
            :key="item.source"
            class="rounded-md border bg-muted/40 px-2 py-1 font-mono"
          >
            {{ item.source }}：保留 {{ item.retainedCount ?? '-' }} / 合格 {{ item.eligibleCount ?? '-' }} 张{{ item.truncated ? '（预算截断）' : '' }}
          </span>
        </div>
        <ul class="mt-2 space-y-1 text-xs text-muted-foreground">
          <li
            v-for="note in latest.limitations"
            :key="note"
          >
            · {{ reasonLabel(note) }}
          </li>
        </ul>
        <p class="mt-2 text-xs text-muted-foreground">
          默认观察有限期限与行权价范围，并排除已知调整合约；比率仅代表筛选范围。Expected Move 是市场隐含范围参考，不是保证或概率区间。
        </p>
      </details>

      <section class="space-y-3.5 rounded-xl border bg-card/50 p-4">
        <h4 class="font-semibold">
          <OptionHelp
            label="波动率与保护需求"
            compact
          />
        </h4>

        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div
            v-for="m in [
              { label: '标准30D ATM IV', value: pct(latest.iv30D) },
              { label: 'IV 分位数', value: latest.ivPercentile == null ? `N/A (${latest.ivSampleCount ?? 0} 样本)` : `${num(latest.ivPercentile)}%` },
              { label: 'IV / RV (20D)', value: num(latest.ivRvRatio) },
              { label: '25Δ Skew 变化', value: pct(latest.skewChange) },
            ]"
            :key="m.label"
            class="rounded-xl border bg-card p-3"
          >
            <p class="text-xs text-muted-foreground">
              <OptionHelp
                :label="m.label"
                compact
              />
            </p>
            <p class="mt-2 font-mono text-lg font-semibold tabular-nums">
              {{ m.value }}
            </p>
          </div>
        </div>

        <p
          v-if="latest.iv30D != null"
          class="text-xs text-muted-foreground"
        >
          标准30D IV来源：{{ latest.ivSource?.join('/') ?? 'N/A' }}；{{ latest.iv30DMethod === 'exact_expiry' ? '实际30D到期日' : '两侧期限总方差插值' }}。
        </p>
        <p
          v-if="latest.iv30D == null"
          class="text-xs text-muted-foreground"
        >
          N/A · 需要有效 ATM Call/Put 与跨30D到期日；历史分位数至少20个同来源可比交易日。RV：20个完整日线对数收益，年化 √252；IV使用ACT/365。
        </p>

        <div class="flex flex-wrap gap-2.5 text-xs">
          <div
            v-for="skew in latest.skewTerms"
            :key="skew.targetDte"
            class="inline-flex items-center gap-1.5 rounded-lg border bg-card px-2.5 py-1.5"
          >
            <OptionHelp
              :label="`${skew.targetDte}D Skew`"
              compact
            />:
            <span class="font-mono font-medium">{{ pct(skew.value) }}</span>
            <span class="text-muted-foreground">
              · {{ skew.actualDte ? `实际 ${skew.actualDte}D (${skew.expiration}, ${skew.source}/${skew.feedType})` : '有效 Delta 不足' }}
            </span>
          </div>
        </div>

        <OptionsCharts
          :latest="latest"
          :history="data?.dailyHistory ?? []"
        />

        <div class="min-w-0 max-w-full overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow class="bg-muted/30">
                <TableHead>
                  <OptionHelp
                    label="实际期限"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="ATM IV"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="Expected Move ($)"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="计算方法"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="来源"
                    compact
                  />
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="term in latest.termStructure"
                :key="term.expiration"
              >
                <TableCell class="font-mono">
                  {{ term.expiration }} · {{ term.dte }}D
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ pct(term.atmIv) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ num(term.expectedMove) }}
                </TableCell>
                <TableCell class="text-xs text-muted-foreground">
                  {{ term.expectedMoveMethod === 'atm_straddle_mid' ? 'ATM Straddle Mid' : 'IV × 标的现价 × √(DTE/365)' }}
                </TableCell>
                <TableCell class="font-mono text-xs">
                  {{ term.source }}/{{ term.feedType }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>

        <div
          v-if="latest.putCallRatios?.length"
          class="space-y-1.5 rounded-xl border bg-card p-3"
        >
          <p class="text-xs font-medium text-muted-foreground">
            <OptionHelp
              label="Put/Call 期限分布"
              compact
            />
          </p>
          <div class="flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span
              v-for="r in latest.putCallRatios"
              :key="r.dteMin"
              class="rounded-md border bg-muted/30 px-2 py-1 font-mono"
            >{{ r.dteMin }}–{{ r.dteMax }}D Put/Call: Volume {{ num(r.volumeRatio) }} · OI {{ num(r.oiRatio) }}</span>
          </div>
        </div>
      </section>

      <section class="space-y-3 rounded-xl border bg-card/50 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h4 class="font-semibold">
            <OptionHelp
              label="期权链"
              compact
            />
          </h4>
          <span class="text-xs text-muted-foreground">
            <OptionHelp
              label="数据来源（独立报价）"
              compact
            />
          </span>
        </div>

        <div class="grid gap-3 sm:grid-cols-3">
          <FieldSelect
            v-model="expiry"
            label="到期日"
            :options="expirations"
          />
          <FieldSelect
            v-model="kind"
            label="合约类型"
            :options="[{ value: 'all', label: 'Call / Put' }, { value: 'call', label: 'Call' }, { value: 'put', label: 'Put' }]"
          />
          <FieldSelect
            v-model="source"
            label="数据来源（独立报价）"
            :options="sources"
          />
        </div>

        <div class="min-w-0 max-w-full overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow class="bg-muted/30">
                <TableHead>
                  <OptionHelp
                    label="类型/Strike"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="Bid / Ask"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="最优可见 Size"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="Volume / OI"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="OI日期"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="IV / Delta"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="Spread / Vol:OI"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="风险与来源"
                    compact
                  />
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="c in chain"
                :key="`${c.symbol}:${c.dataSource}`"
              >
                <TableCell>
                  <p class="font-medium">
                    <span :class="c.optionType === 'put' ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'">
                      {{ c.optionType }}
                    </span>
                    <span class="ml-1 font-mono">{{ num(c.strike) }}</span>
                  </p>
                  <p class="max-w-36 break-all font-mono text-xs text-muted-foreground">
                    {{ c.symbol }}
                  </p>
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ num(c.bid) }} / {{ num(c.ask) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ num(c.bidSize, 0) }} / {{ num(c.askSize, 0) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ num(c.volume, 0) }} / {{ num(c.openInterest, 0) }}
                  <p class="font-sans text-xs text-muted-foreground">
                    Volume 日期 {{ c.volumeDate ?? 'N/A' }}
                  </p>
                </TableCell>
                <TableCell class="font-mono text-xs">
                  {{ c.oiDate ?? 'N/A · 日期未知' }}
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ pct(c.iv) }} / {{ num(c.delta) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums">
                  {{ pct(c.spread) }} / {{ num(c.volumeOi) }}
                </TableCell>
                <TableCell class="max-w-48 whitespace-normal">
                  <p class="font-medium text-orange-600 dark:text-orange-400">
                    研究风险 {{ num(c.observedRisk?.value ?? c.risk.value) }}
                  </p>
                  <p class="text-xs">
                    {{ c.feedType }} · {{ reasonLabel(c.quoteStatus) }}
                  </p>
                  <p
                    v-if="!c.quoteTimestamp"
                    class="text-xs text-muted-foreground"
                  >
                    报价时间 N/A
                  </p>
                  <p
                    v-else
                    class="text-xs text-muted-foreground"
                  >
                    {{ formatDateTimeInDisplayTimezone(c.quoteTimestamp) }}
                  </p>
                  <p
                    v-if="c.notes.length"
                    class="text-xs text-muted-foreground"
                  >
                    {{ c.notes.map(reasonLabel).join(' · ') }}
                  </p>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <p
            v-if="!chain.length"
            class="p-6 text-center text-sm text-muted-foreground"
          >
            此筛选没有合约
          </p>
        </div>
      </section>

      <section class="space-y-3 rounded-xl border bg-card/50 p-4">
        <h4 class="font-semibold">
          <OptionHelp
            label="异常合约与规则"
            compact
          />
        </h4>
        <p
          v-if="!anomalies.length"
          class="text-sm text-muted-foreground"
        >
          暂无满足规则的异常；不表示风险为零。
        </p>
        <details
          v-for="e in anomalies"
          :key="`${e.contractSymbol}:${e.eventType}:${e.source}`"
          class="rounded-xl border bg-card p-3.5"
        >
          <summary class="cursor-pointer text-sm font-medium">
            {{ eventLabels[e.eventType] }} · <span class="font-mono">{{ e.contractSymbol || symbol }}</span> · 异常程度 {{ num(e.severity) }} · 证据 {{ e.evidenceGrade }}
          </summary>
          <p class="mt-2 text-sm">
            {{ e.explanation }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            原值 {{ num(e.value) }} · {{ e.source }}/{{ e.feedType }} · {{ formatDateTimeInDisplayTimezone(e.dataTime) }}
          </p>
          <div
            v-if="e.reference && Object.keys(e.reference).length"
            class="mt-2.5 flex flex-wrap gap-2 text-xs"
          >
            <span
              v-for="[k, v] in Object.entries(e.reference)"
              :key="k"
              class="rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-muted-foreground"
            >
              {{ refLabels[k] ?? k }}: {{ formatRefValue(v) }}
            </span>
          </div>
        </details>
      </section>

      <section
        v-if="latest.llmAnalysis"
        class="space-y-2.5 rounded-xl border bg-card p-4"
      >
        <h4 class="font-semibold">
          <OptionHelp
            label="辅助解释"
            compact
          />
        </h4>
        <p class="text-sm leading-relaxed">
          {{ latest.llmAnalysis.whyItMatters }}
        </p>
        <p class="text-sm text-muted-foreground">
          {{ latest.llmAnalysis.protectionVsDirection }}
        </p>
        <div
          v-for="group in [
            { name: '可能事件', items: latest.llmAnalysis.possibleCatalysts },
            { name: '其他解释', items: latest.llmAnalysis.alternativeExplanations },
            { name: '数据限制', items: latest.llmAnalysis.dataLimits },
            { name: '交易风险', items: latest.llmAnalysis.tradingRisks },
          ]"
          :key="group.name"
        >
          <p class="text-xs font-semibold">
            {{ group.name }}
          </p>
          <ul class="mt-1 space-y-0.5 text-sm text-muted-foreground">
            <li
              v-for="text in group.items"
              :key="text"
            >
              · {{ text }}
            </li>
          </ul>
        </div>
      </section>

      <section class="space-y-3 rounded-xl border bg-card/50 p-4">
        <h4 class="font-semibold">
          <OptionHelp
            label="历史异常与事后验证"
            compact
          />
        </h4>
        <p class="text-xs text-muted-foreground">
          收益以首次可知时间后的首个有效开盘为基准（盘前可用当天），按1/3/5交易日精确对齐。缺失不顺延，事后结果不修改原始信号。
        </p>
        <p
          v-if="!data?.events.length"
          class="text-sm text-muted-foreground"
        >
          暂无历史事件
        </p>
        <details
          v-for="e in data?.events"
          :key="e.id"
          class="rounded-xl border bg-card p-3.5"
        >
          <summary class="cursor-pointer text-sm font-medium">
            {{ e.tradeDate }} · {{ eventLabels[e.eventType] }} · <span class="font-mono">{{ e.contractSymbol || symbol }}</span> · {{ e.dataSource }}/{{ e.feedType }}
          </summary>
          <p class="mt-2 text-sm">
            {{ e.initialEvidence.explanation }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            首次可知 {{ formatDateTimeInDisplayTimezone(e.occurredAt) }} · 最新 {{ formatDateTimeInDisplayTimezone(e.updatedAt) }} · 原值 {{ num(e.initialEvidence.value) }} / 最新 {{ num(e.latestEvidence.value) }}
          </p>
          <p
            v-if="e.validation.oiConfirmation"
            class="mt-2 text-sm"
          >
            OI次日验证：{{ e.validation.oiConfirmation.oiDate }} {{ e.validation.oiConfirmation.change > 0 ? '+' : '' }}{{ num(e.validation.oiConfirmation.change, 0) }} · 可知时间 {{ formatDateTimeInDisplayTimezone(e.validation.oiConfirmation.knownAt) }}
          </p>
          <div class="mt-2 flex flex-wrap gap-4 font-mono text-sm">
            <span
              v-for="r in e.evaluation.returns"
              :key="r.days"
            >{{ r.days }}D: {{ pct(r.value) }} ({{ r.status }})</span>
            <span>5D 最大不利波动 {{ pct(e.evaluation.maxAdverse5D) }}</span>
            <span>后续RV {{ pct(e.evaluation.subsequentRv20D) }} / 变化 {{ pct(e.evaluation.rvChange) }}</span>
          </div>
          <p
            v-for="(returns, benchmark) in e.evaluation.benchmarks"
            :key="benchmark"
            class="mt-1 font-mono text-xs text-muted-foreground"
          >
            {{ benchmark }}: {{ returns.map(r => `${r.days}D ${pct(r.value)}`).join(' · ') }}
          </p>
        </details>
      </section>

      <section
        v-if="data?.dailyHistory.length"
        class="space-y-2 rounded-xl border bg-card/50 p-4"
      >
        <h4 class="font-semibold">
          <OptionHelp
            label="日度评分历史"
            compact
          />
        </h4>
        <div class="min-w-0 max-w-full overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow class="bg-muted/30">
                <TableHead>
                  <OptionHelp
                    label="交易日"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="看跌保护"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="异常活动"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="流动性风险"
                    compact
                  />
                </TableHead>
                <TableHead>
                  <OptionHelp
                    label="证据"
                    compact
                  />
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="h in [...data.dailyHistory].reverse()"
                :key="h.tradeDate"
              >
                <TableCell class="font-mono">
                  {{ h.tradeDate }}
                </TableCell>
                <TableCell class="font-mono tabular-nums text-red-600 dark:text-red-400">
                  {{ num(h.scores?.bearishDemand.value) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums text-amber-600 dark:text-amber-400">
                  {{ num(h.scores?.unusualActivity.value) }}
                </TableCell>
                <TableCell class="font-mono tabular-nums text-orange-600 dark:text-orange-400">
                  {{ num(h.scores?.liquidityRisk.value) }}
                </TableCell>
                <TableCell class="font-mono">
                  {{ h.evidenceGrade }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>

      <section
        v-if="data?.analyses.length"
        class="space-y-2 rounded-xl border bg-card/50 p-4"
      >
        <h4 class="font-semibold">
          <OptionHelp
            label="解释历史"
            compact
          />
        </h4>
        <details
          v-for="a in data.analyses"
          :key="a.createdAt"
          class="rounded-xl border bg-card p-3.5"
        >
          <summary class="cursor-pointer text-sm font-medium">
            {{ formatDateTimeInDisplayTimezone(a.createdAt) }} · {{ a.model }}
          </summary>
          <p class="mt-2 text-sm">
            {{ a.explanation.whyItMatters }}
          </p>
          <p class="mt-1 text-sm text-muted-foreground">
            {{ a.explanation.protectionVsDirection }}
          </p>
        </details>
      </section>
    </template>
  </div>
</template>
