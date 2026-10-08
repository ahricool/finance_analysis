<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { optionsIntelligenceApi, type OptionsDetail } from '@/api/optionsIntelligence';
import { tasksApi } from '@/api/tasks';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import OptionsScores from './OptionsScores.vue';
import OptionsCharts from './OptionsCharts.vue';
import { eventLabels, formatOptionNumber as num, formatOptionPct as pct, reasonLabel } from './labels';
const props = defineProps<{ symbol: string }>();
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
async function load(version = generation) {
  loading.value = true;
  try {
    const response = await optionsIntelligenceApi.detail(props.symbol);
    if (version !== generation) return;
    data.value = response;
    if (!expirations.value.some(e => e.value === expiry.value)) expiry.value = expirations.value[0]?.value ?? '';
    if (!sources.value.some(s => s.value === source.value)) source.value = sources.value[0]?.value ?? 'yfinance';
  } catch (e) { if (version === generation) error.value = getParsedApiError(e); }
  finally { if (version === generation) loading.value = false; }
}
async function poll(id: string, version: number) {
  try {
    const task = await tasksApi.getTaskRunDetail(id);
    if (version !== generation) return;
    if (['completed', 'failed', 'cancelled', 'skipped'].includes(task.status)) {
      working.value = false;
      if (task.status !== 'completed') error.value = getParsedApiError(new Error(task.error || task.message || '任务未完成，请在任务中心查看原因'));
      await load(version);
      return;
    }
    timer = setTimeout(() => { void poll(id, version); }, 3000);
  } catch (e) { if (version === generation) { working.value = false; error.value = getParsedApiError(e); } }
}
async function refresh(explain = false) {
  const version = generation;
  working.value = true; error.value = null;
  try {
    const task = await optionsIntelligenceApi.refresh(props.symbol, explain);
    if (version !== generation) return;
    taskId.value = task.taskId;
    void poll(task.taskId, version);
  } catch (e) { if (version === generation) { error.value = getParsedApiError(e); working.value = false; } }
}
watch(() => props.symbol, () => {
  generation++; clearTimeout(timer); expiry.value = ''; source.value = 'yfinance';
  data.value = null; error.value = null; taskId.value = ''; working.value = false;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { generation++; clearTimeout(timer); });
</script>
<template>
  <div
    class="min-w-0 space-y-5"
    data-testid="options-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="font-semibold">
          期权情报 <span class="text-xs font-normal text-muted-foreground">Options Intelligence</span>
        </h3><p class="text-xs text-muted-foreground">
          {{ latest?.evidenceGrade ? `证据 ${latest.evidenceGrade} · ${latest.status === 'warming_up' ? '历史预热' : '已采集'}` : '尚未采集' }} · {{ formatDateTimeInDisplayTimezone(latest?.observedAt) }}
        </p>
      </div>
      <div class="flex gap-2">
        <LoadingButton
          :loading="working"
          @click="refresh()"
        >
          刷新期权链
        </LoadingButton><Button
          variant="outline"
          :disabled="working || !latest"
          @click="refresh(true)"
        >
          解释异常
        </Button>
      </div>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />
    <p
      v-if="taskId"
      class="text-xs text-muted-foreground"
    >
      {{ working ? '任务执行中，可离开页面稍后查看' : '任务已结束' }} · <RouterLink
        class="underline"
        :to="{ path: '/tasks/runs', query: { taskId } }"
      >
        查看任务 {{ taskId }}
      </RouterLink>
    </p>
    <p
      v-if="loading && !data"
      class="text-sm text-muted-foreground"
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
      <OptionsScores :scores="latest.scores" />
      <p class="text-sm text-muted-foreground">
        {{ latest.riskSummary }}
      </p>
      <details class="rounded-xl border p-3 text-sm">
        <summary class="cursor-pointer">
          数据限制 · 历史 {{ latest.historyDays }} 个可比交易日
        </summary><ul class="mt-2 space-y-1 text-xs text-muted-foreground">
          <li
            v-for="note in latest.limitations"
            :key="note"
          >
            {{ reasonLabel(note) }}
          </li>
        </ul><p class="mt-2 text-xs">
          默认观察有限期限与行权价范围，并排除已知调整合约；比率仅代表筛选范围。Expected Move 是市场隐含范围参考，不是保证或概率区间。
        </p>
      </details>
      <section class="space-y-3">
        <h4 class="font-semibold">
          波动率与保护需求
        </h4>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div
            v-for="m in [{ label: '标准30D ATM IV', value: pct(latest.iv30D) }, { label: 'IV 分位数', value: latest.ivPercentile == null ? `N/A (${latest.ivSampleCount ?? 0} 样本)` : `${num(latest.ivPercentile)}%` }, { label: 'IV / RV (20D)', value: num(latest.ivRvRatio) }, { label: '25Δ Skew 变化', value: pct(latest.skewChange) }]"
            :key="m.label"
            class="rounded-xl border p-3"
          >
            <p class="text-xs text-muted-foreground">
              {{ m.label }}
            </p><p class="mt-2 font-semibold tabular-nums">
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
        <div class="flex flex-wrap gap-3 text-sm">
          <span
            v-for="skew in latest.skewTerms"
            :key="skew.targetDte"
          >{{ skew.targetDte }}D Skew: {{ pct(skew.value) }} · {{ skew.actualDte ? `实际 ${skew.actualDte}D (${skew.expiration}, ${skew.source}/${skew.feedType})` : '有效 Delta 不足' }}</span>
        </div>
        <OptionsCharts
          :latest="latest"
          :history="data?.dailyHistory ?? []"
        />
        <div class="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>实际期限</TableHead><TableHead>ATM IV</TableHead><TableHead>Expected Move ($)</TableHead><TableHead>计算方法</TableHead><TableHead>来源</TableHead></TableRow></TableHeader><TableBody>
              <TableRow
                v-for="term in latest.termStructure"
                :key="term.expiration"
              >
                <TableCell>{{ term.expiration }} · {{ term.dte }}D</TableCell><TableCell>{{ pct(term.atmIv) }}</TableCell><TableCell>{{ num(term.expectedMove) }}</TableCell><TableCell>{{ term.expectedMoveMethod === 'atm_straddle_mid' ? 'ATM Straddle Mid' : 'IV × 标的现价 × √(DTE/365)' }}</TableCell><TableCell>{{ term.source }}/{{ term.feedType }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p class="text-xs text-muted-foreground">
          <span
            v-for="r in latest.putCallRatios"
            :key="r.dteMin"
            class="mr-4"
          >{{ r.dteMin }}–{{ r.dteMax }}D Put/Call: Volume {{ num(r.volumeRatio) }} · OI {{ num(r.oiRatio) }}</span>
        </p>
      </section>
      <section class="space-y-3">
        <h4 class="font-semibold">
          期权链
        </h4>
        <div class="grid gap-3 sm:grid-cols-3">
          <FieldSelect
            v-model="expiry"
            label="到期日"
            :options="expirations"
          /><FieldSelect
            v-model="kind"
            label="合约类型"
            :options="[{ value: 'all', label: 'Call / Put' }, { value: 'call', label: 'Call' }, { value: 'put', label: 'Put' }]"
          /><FieldSelect
            v-model="source"
            label="数据来源（独立报价）"
            :options="sources"
          />
        </div>
        <div class="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader><TableRow><TableHead>类型/Strike</TableHead><TableHead>Bid / Ask</TableHead><TableHead>最优可见 Size</TableHead><TableHead>Volume / OI</TableHead><TableHead>OI日期</TableHead><TableHead>IV / Delta</TableHead><TableHead>Spread / Vol:OI</TableHead><TableHead>风险与来源</TableHead></TableRow></TableHeader><TableBody>
              <TableRow
                v-for="c in chain"
                :key="`${c.symbol}:${c.dataSource}`"
              >
                <TableCell>
                  <p>{{ c.optionType }} {{ num(c.strike) }}</p><p class="max-w-36 break-all text-xs text-muted-foreground">
                    {{ c.symbol }}
                  </p>
                </TableCell><TableCell>{{ num(c.bid) }} / {{ num(c.ask) }}</TableCell><TableCell>{{ num(c.bidSize, 0) }} / {{ num(c.askSize, 0) }}</TableCell><TableCell>
                  {{ num(c.volume, 0) }} / {{ num(c.openInterest, 0) }}
                  <p class="text-xs text-muted-foreground">
                    Volume 日期 {{ c.volumeDate ?? 'N/A' }}
                  </p>
                </TableCell><TableCell>{{ c.oiDate ?? 'N/A · 日期未知' }}</TableCell><TableCell>{{ pct(c.iv) }} / {{ num(c.delta) }}</TableCell><TableCell>{{ pct(c.spread) }} / {{ num(c.volumeOi) }}</TableCell><TableCell class="max-w-48 whitespace-normal">
                  <p class="text-orange-600 dark:text-orange-400">
                    风险 {{ num(c.risk.value) }}
                  </p><p class="text-xs">
                    {{ c.feedType }} · {{ reasonLabel(c.quoteStatus) }}
                  </p><p
                    v-if="!c.quoteTimestamp"
                    class="text-xs text-muted-foreground"
                  >
                    报价时间 N/A
                  </p><p
                    v-else
                    class="text-xs text-muted-foreground"
                  >
                    {{ formatDateTimeInDisplayTimezone(c.quoteTimestamp) }}
                  </p><p class="text-xs text-muted-foreground">
                    {{ c.notes.map(reasonLabel).join(' · ') }}
                  </p>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table><p
            v-if="!chain.length"
            class="p-6 text-center text-sm text-muted-foreground"
          >
            此筛选没有合约
          </p>
        </div>
      </section>
      <section class="space-y-3">
        <h4 class="font-semibold">
          异常合约与规则
        </h4><p
          v-if="!anomalies.length"
          class="text-sm text-muted-foreground"
        >
          暂无满足规则的异常；不表示风险为零。
        </p><details
          v-for="e in anomalies"
          :key="`${e.contractSymbol}:${e.eventType}:${e.source}`"
          class="rounded-xl border p-3"
        >
          <summary class="cursor-pointer text-sm">
            {{ eventLabels[e.eventType] }} · {{ e.contractSymbol || symbol }} · 异常程度 {{ num(e.severity) }} · 证据 {{ e.evidenceGrade }}
          </summary><p class="mt-2 text-sm">
            {{ e.explanation }}
          </p><p class="text-xs text-muted-foreground">
            原值 {{ num(e.value) }} · {{ e.source }}/{{ e.feedType }} · {{ formatDateTimeInDisplayTimezone(e.dataTime) }}
          </p><pre class="mt-2 overflow-auto text-xs text-muted-foreground">{{ JSON.stringify(e.reference, null, 2) }}</pre>
        </details>
      </section>
      <section
        v-if="latest.llmAnalysis"
        class="space-y-2 rounded-xl border p-4"
      >
        <h4 class="font-semibold">
          辅助解释
        </h4><p class="text-sm">
          {{ latest.llmAnalysis.whyItMatters }}
        </p><p class="text-sm">
          {{ latest.llmAnalysis.protectionVsDirection }}
        </p><div
          v-for="group in [{ name: '可能事件', items: latest.llmAnalysis.possibleCatalysts }, { name: '其他解释', items: latest.llmAnalysis.alternativeExplanations }, { name: '数据限制', items: latest.llmAnalysis.dataLimits }, { name: '交易风险', items: latest.llmAnalysis.tradingRisks }]"
          :key="group.name"
        >
          <p class="text-xs font-semibold">
            {{ group.name }}
          </p><ul class="text-sm text-muted-foreground">
            <li
              v-for="text in group.items"
              :key="text"
            >
              {{ text }}
            </li>
          </ul>
        </div>
      </section>
      <section class="space-y-3">
        <h4 class="font-semibold">
          历史异常与事后验证
        </h4><p class="text-xs text-muted-foreground">
          收益以首次可知时间后的首个有效开盘为基准（盘前可用当天），按1/3/5交易日精确对齐。缺失不顺延，事后结果不修改原始信号。
        </p><p
          v-if="!data?.events.length"
          class="text-sm text-muted-foreground"
        >
          暂无历史事件
        </p><details
          v-for="e in data?.events"
          :key="e.id"
          class="rounded-xl border p-3"
        >
          <summary class="cursor-pointer text-sm">
            {{ e.tradeDate }} · {{ eventLabels[e.eventType] }} · {{ e.contractSymbol || symbol }} · {{ e.dataSource }}/{{ e.feedType }}
          </summary><p class="mt-2 text-sm">
            {{ e.initialEvidence.explanation }}
          </p><p class="text-xs text-muted-foreground">
            首次可知 {{ formatDateTimeInDisplayTimezone(e.occurredAt) }} · 最新 {{ formatDateTimeInDisplayTimezone(e.updatedAt) }} · 原值 {{ num(e.initialEvidence.value) }} / 最新 {{ num(e.latestEvidence.value) }}
          </p><p
            v-if="e.validation.oiConfirmation"
            class="mt-2 text-sm"
          >
            OI次日验证：{{ e.validation.oiConfirmation.oiDate }} {{ e.validation.oiConfirmation.change > 0 ? '+' : '' }}{{ num(e.validation.oiConfirmation.change, 0) }} · 可知时间 {{ formatDateTimeInDisplayTimezone(e.validation.oiConfirmation.knownAt) }}
          </p><div class="mt-2 flex flex-wrap gap-4 text-sm">
            <span
              v-for="r in e.evaluation.returns"
              :key="r.days"
            >{{ r.days }}D: {{ pct(r.value) }} ({{ r.status }})</span><span>5D 最大不利波动 {{ pct(e.evaluation.maxAdverse5D) }}</span><span>后续RV {{ pct(e.evaluation.subsequentRv20D) }} / 变化 {{ pct(e.evaluation.rvChange) }}</span>
          </div><p
            v-for="(returns, benchmark) in e.evaluation.benchmarks"
            :key="benchmark"
            class="mt-1 text-xs text-muted-foreground"
          >
            {{ benchmark }}: {{ returns.map(r => `${r.days}D ${pct(r.value)}`).join(' · ') }}
          </p>
        </details>
      </section>
      <section
        v-if="data?.dailyHistory.length"
        class="space-y-2"
      >
        <h4 class="font-semibold">
          日度评分历史
        </h4><div class="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>交易日</TableHead><TableHead>看跌保护</TableHead><TableHead>异常活动</TableHead><TableHead>流动性风险</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>
              <TableRow
                v-for="h in [...data.dailyHistory].reverse()"
                :key="h.tradeDate"
              >
                <TableCell>{{ h.tradeDate }}</TableCell><TableCell class="text-red-600">
                  {{ num(h.scores?.bearishDemand.value) }}
                </TableCell><TableCell class="text-amber-600">
                  {{ num(h.scores?.unusualActivity.value) }}
                </TableCell><TableCell class="text-orange-600">
                  {{ num(h.scores?.liquidityRisk.value) }}
                </TableCell><TableCell>{{ h.evidenceGrade }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>
      <section
        v-if="data?.analyses.length"
        class="space-y-2"
      >
        <h4 class="font-semibold">
          解释历史
        </h4><details
          v-for="a in data.analyses"
          :key="a.createdAt"
          class="rounded-xl border p-3"
        >
          <summary class="cursor-pointer text-sm">
            {{ formatDateTimeInDisplayTimezone(a.createdAt) }} · {{ a.model }}
          </summary><p class="mt-2 text-sm">
            {{ a.explanation.whyItMatters }}
          </p><p class="text-sm text-muted-foreground">
            {{ a.explanation.protectionVsDirection }}
          </p>
        </details>
      </section>
    </template>
  </div>
</template>
