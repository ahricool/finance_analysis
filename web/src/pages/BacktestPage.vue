<script setup lang="ts">
import { backtestApi } from '@/api/backtest';
import type { ParsedApiError } from '@/api/error';
import { getParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Card from '@/components/common/Card.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import HorizontalScrollArea from '@/components/common/HorizontalScrollArea.vue';
import Pagination from '@/components/common/Pagination.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import Tooltip from '@/components/common/Tooltip.vue';
import type { BacktestResultItem, BacktestRunResponse, PerformanceMetrics } from '@/types/backtest';
import { Check, Minus, X } from 'lucide-vue-next';
import { computed, onMounted, ref } from 'vue';

const BACKTEST_INPUT_CLASS =
  'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const BACKTEST_COMPACT_INPUT_CLASS =
  'input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 py-2 text-xs transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';

function pct(value?: number | null): string {
  if (value == null) return '--';
  return `${value.toFixed(1)}%`;
}

function statusBadgeVariant(
  status: string,
): 'default' | 'success' | 'warning' | 'danger' {
  if (status === 'completed') return 'success';
  if (status === 'insufficient' || status === 'insufficient_data') return 'warning';
  if (status === 'error') return 'danger';
  return 'default';
}

function statusBadgeLabel(status: string): string {
  if (status === 'insufficient' || status === 'insufficient_data') return 'insufficient';
  return status;
}

const codeFilter = ref('');
const analysisDateFrom = ref('');
const analysisDateTo = ref('');
const evalDays = ref('');
const forceRerun = ref(false);
const isRunning = ref(false);
const runResult = ref<BacktestRunResponse | null>(null);
const runError = ref<ParsedApiError | null>(null);
const pageError = ref<ParsedApiError | null>(null);
const results = ref<BacktestResultItem[]>([]);
const totalResults = ref(0);
const currentPage = ref(1);
const isLoadingResults = ref(false);
const pageSize = 20;
const overallPerf = ref<PerformanceMetrics | null>(null);
const stockPerf = ref<PerformanceMetrics | null>(null);
const isLoadingPerf = ref(false);

const effectiveWindowDays = computed(() =>
  evalDays.value ? parseInt(evalDays.value, 10) : overallPerf.value?.evalWindowDays,
);
const isNextDayValidation = computed(() => effectiveWindowDays.value === 1);
const showNextDayActualColumns = computed(() => isNextDayValidation.value);
const totalPages = computed(() => Math.ceil(totalResults.value / pageSize));

onMounted(() => {
  void (async () => {
    const overall = await backtestApi.getOverallPerformance();
    overallPerf.value = overall;
    const windowDays = overall?.evalWindowDays;
    if (windowDays && !evalDays.value) {
      evalDays.value = String(windowDays);
    }
    await fetchResults(1, undefined, windowDays, undefined, undefined);
  })();
});

async function fetchResults(
  page = 1,
  code?: string,
  windowDays?: number,
  startDate?: string,
  endDate?: string,
) {
  isLoadingResults.value = true;
  try {
    const response = await backtestApi.getResults({
      code: code || undefined,
      evalWindowDays: windowDays,
      analysisDateFrom: startDate || undefined,
      analysisDateTo: endDate || undefined,
      page,
      limit: pageSize,
    });
    results.value = response.items;
    totalResults.value = response.total;
    currentPage.value = response.page;
    pageError.value = null;
  } catch (err) {
    console.error('Failed to fetch backtest results:', err);
    pageError.value = getParsedApiError(err);
  } finally {
    isLoadingResults.value = false;
  }
}

async function fetchPerformance(
  code?: string,
  windowDays?: number,
  startDate?: string,
  endDate?: string,
) {
  isLoadingPerf.value = true;
  try {
    const overall = await backtestApi.getOverallPerformance({
      evalWindowDays: windowDays,
      analysisDateFrom: startDate || undefined,
      analysisDateTo: endDate || undefined,
    });
    overallPerf.value = overall;

    if (code) {
      const stock = await backtestApi.getStockPerformance(code, {
        evalWindowDays: windowDays,
        analysisDateFrom: startDate || undefined,
        analysisDateTo: endDate || undefined,
      });
      stockPerf.value = stock;
    } else {
      stockPerf.value = null;
    }
    pageError.value = null;
  } catch (err) {
    console.error('Failed to fetch performance:', err);
    pageError.value = getParsedApiError(err);
  } finally {
    isLoadingPerf.value = false;
  }
}

async function handleRun() {
  isRunning.value = true;
  runResult.value = null;
  runError.value = null;
  try {
    const code = codeFilter.value.trim() || undefined;
    const evalWindowDays = evalDays.value ? parseInt(evalDays.value, 10) : undefined;
    const response = await backtestApi.run({
      code,
      force: forceRerun.value || undefined,
      minAgeDays: forceRerun.value ? 0 : undefined,
      evalWindowDays,
    });
    runResult.value = response;
    await fetchResults(1, codeFilter.value.trim() || undefined, evalWindowDays, analysisDateFrom.value, analysisDateTo.value);
    await fetchPerformance(codeFilter.value.trim() || undefined, evalWindowDays, analysisDateFrom.value, analysisDateTo.value);
  } catch (err) {
    runError.value = getParsedApiError(err);
  } finally {
    isRunning.value = false;
  }
}

function handleFilter() {
  const code = codeFilter.value.trim() || undefined;
  const windowDays = evalDays.value ? parseInt(evalDays.value, 10) : undefined;
  currentPage.value = 1;
  void fetchResults(1, code, windowDays, analysisDateFrom.value, analysisDateTo.value);
  void fetchPerformance(code, windowDays, analysisDateFrom.value, analysisDateTo.value);
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    handleFilter();
  }
}

function handleShowNextDay() {
  const code = codeFilter.value.trim() || undefined;
  evalDays.value = '1';
  currentPage.value = 1;
  void fetchResults(1, code, 1, analysisDateFrom.value, analysisDateTo.value);
  void fetchPerformance(code, 1, analysisDateFrom.value, analysisDateTo.value);
}

function handlePageChange(page: number) {
  const windowDays = evalDays.value ? parseInt(evalDays.value, 10) : undefined;
  void fetchResults(page, codeFilter.value.trim() || undefined, windowDays, analysisDateFrom.value, analysisDateTo.value);
}

function onCodeInput(e: Event) {
  codeFilter.value = (e.target as HTMLInputElement).value.toUpperCase();
}
</script>

<template>
  <div class="min-h-full flex flex-col rounded-[1.5rem] bg-transparent">
    <header class="flex-shrink-0 border-b border-white/5 px-3 py-3 sm:px-4">
      <div class="flex w-full flex-wrap items-center gap-2">
        <div class="relative min-w-0 flex-[1_1_220px]">
          <input
            type="text"
            :value="codeFilter"
            :disabled="isRunning"
            :class="BACKTEST_INPUT_CLASS"
            placeholder="Filter by stock code (leave empty for all)"
            @input="onCodeInput"
            @keydown="handleKeyDown"
          />
        </div>
        <button
          type="button"
          :disabled="isLoadingResults"
          class="btn-secondary flex items-center gap-1.5 whitespace-nowrap"
          @click="handleFilter"
        >
          Filter
        </button>
        <div class="flex items-center gap-2 whitespace-nowrap lg:w-40 lg:justify-between">
          <span class="text-xs text-muted-text">Window</span>
          <input
            v-model="evalDays"
            type="number"
            min="1"
            max="120"
            placeholder="10"
            :disabled="isRunning"
            :class="`${BACKTEST_COMPACT_INPUT_CLASS} w-24 text-center tabular-nums`"
          />
        </div>
        <div class="flex items-center gap-2 whitespace-nowrap">
          <span class="text-xs text-muted-text">From</span>
          <input
            v-model="analysisDateFrom"
            type="date"
            aria-label="Analysis date from"
            :disabled="isRunning"
            :class="`${BACKTEST_COMPACT_INPUT_CLASS} w-40 text-center tabular-nums`"
            @keydown="handleKeyDown"
          />
        </div>
        <div class="flex items-center gap-2 whitespace-nowrap">
          <span class="text-xs text-muted-text">To</span>
          <input
            v-model="analysisDateTo"
            type="date"
            aria-label="Analysis date to"
            :disabled="isRunning"
            :class="`${BACKTEST_COMPACT_INPUT_CLASS} w-40 text-center tabular-nums`"
            @keydown="handleKeyDown"
          />
        </div>
        <button
          type="button"
          :disabled="isLoadingResults || isLoadingPerf"
          :class="['backtest-force-btn', isNextDayValidation ? 'active' : '']"
          @click="handleShowNextDay"
        >
          <span class="dot" />
          1D Validation
        </button>
        <button
          type="button"
          :disabled="isRunning"
          :class="['backtest-force-btn', forceRerun ? 'active' : '']"
          @click="forceRerun = !forceRerun"
        >
          <span class="dot" />
          Force
        </button>
        <button
          type="button"
          :disabled="isRunning"
          class="btn-primary flex items-center gap-1.5 whitespace-nowrap"
          @click="handleRun"
        >
          <template v-if="isRunning">
            <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            Running...
          </template>
          <template v-else>Run Backtest</template>
        </button>
      </div>
      <div v-if="runResult" class="mt-2 w-full">
        <div class="backtest-summary animate-fade-in">
          <span class="label">Processed: <span class="value">{{ runResult.processed }}</span></span>
          <span class="label">Saved: <span class="value primary">{{ runResult.saved }}</span></span>
          <span class="label">Completed: <span class="value success">{{ runResult.completed }}</span></span>
          <span class="label">Insufficient: <span class="value warning">{{ runResult.insufficient }}</span></span>
          <span v-if="runResult.errors > 0" class="label">
            Errors: <span class="value danger">{{ runResult.errors }}</span>
          </span>
        </div>
      </div>
      <ApiErrorAlert v-if="runError" :error="runError" class="mt-2 w-full" />
      <p class="mt-2 text-xs text-muted-text">
        {{
          isNextDayValidation
            ? 'Next-day validation mode compares AI predictions with the next trading day close.'
            : 'Use window = 1 to review AI predictions against the next trading day close.'
        }}
      </p>
    </header>

    <main class="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 lg:flex-row">
      <div class="flex max-h-[38vh] flex-col gap-3 overflow-y-auto lg:max-h-none lg:w-60 lg:flex-shrink-0">
        <div v-if="isLoadingPerf" class="flex items-center justify-center py-8">
          <div class="backtest-spinner sm" />
        </div>
        <Card
          v-else-if="overallPerf"
          variant="gradient"
          padding="md"
          class="animate-fade-in"
        >
          <div class="mb-3">
            <span class="label-uppercase">Overall Performance</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Direction Accuracy</span>
            <span class="value accent">{{ pct(overallPerf.directionAccuracyPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Win Rate</span>
            <span class="value accent">{{ pct(overallPerf.winRatePct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Sim. Return</span>
            <span class="value">{{ pct(overallPerf.avgSimulatedReturnPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Stock Return</span>
            <span class="value">{{ pct(overallPerf.avgStockReturnPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">SL Trigger Rate</span>
            <span class="value">{{ pct(overallPerf.stopLossTriggerRate) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">TP Trigger Rate</span>
            <span class="value">{{ pct(overallPerf.takeProfitTriggerRate) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Days to Hit</span>
            <span class="value">
              {{ overallPerf.avgDaysToFirstHit != null ? overallPerf.avgDaysToFirstHit.toFixed(1) : '--' }}
            </span>
          </div>
          <div class="backtest-metric-footer">
            <span class="text-xs text-muted-text">Evaluations</span>
            <span class="text-xs text-secondary-text font-mono">
              {{ Number(overallPerf.completedCount) }} / {{ Number(overallPerf.totalEvaluations) }}
            </span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-muted-text">W / L / N</span>
            <span class="text-xs font-mono">
              <span class="text-success">{{ overallPerf.winCount }}</span>
              /
              <span class="text-danger">{{ overallPerf.lossCount }}</span>
              /
              <span class="text-warning">{{ overallPerf.neutralCount }}</span>
            </span>
          </div>
        </Card>
        <EmptyState
          v-else
          title="No Metrics Yet"
          description="Run a backtest to generate aggregate performance metrics."
          class="h-full min-h-[12rem] border-dashed bg-card/45 shadow-none"
        />

        <Card
          v-if="stockPerf"
          variant="gradient"
          padding="md"
          class="animate-fade-in"
        >
          <div class="mb-3">
            <span class="label-uppercase">{{ stockPerf.code || codeFilter }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Direction Accuracy</span>
            <span class="value accent">{{ pct(stockPerf.directionAccuracyPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Win Rate</span>
            <span class="value accent">{{ pct(stockPerf.winRatePct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Sim. Return</span>
            <span class="value">{{ pct(stockPerf.avgSimulatedReturnPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Stock Return</span>
            <span class="value">{{ pct(stockPerf.avgStockReturnPct) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">SL Trigger Rate</span>
            <span class="value">{{ pct(stockPerf.stopLossTriggerRate) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">TP Trigger Rate</span>
            <span class="value">{{ pct(stockPerf.takeProfitTriggerRate) }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">Avg Days to Hit</span>
            <span class="value">
              {{ stockPerf.avgDaysToFirstHit != null ? stockPerf.avgDaysToFirstHit.toFixed(1) : '--' }}
            </span>
          </div>
          <div class="backtest-metric-footer">
            <span class="text-xs text-muted-text">Evaluations</span>
            <span class="text-xs text-secondary-text font-mono">
              {{ Number(stockPerf.completedCount) }} / {{ Number(stockPerf.totalEvaluations) }}
            </span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-muted-text">W / L / N</span>
            <span class="text-xs font-mono">
              <span class="text-success">{{ stockPerf.winCount }}</span>
              /
              <span class="text-danger">{{ stockPerf.lossCount }}</span>
              /
              <span class="text-warning">{{ stockPerf.neutralCount }}</span>
            </span>
          </div>
        </Card>
      </div>

      <section class="min-h-0 flex-1 overflow-y-auto">
        <ApiErrorAlert v-if="pageError" :error="pageError" class="mb-3" />
        <div v-if="isLoadingResults" class="flex flex-col items-center justify-center h-64">
          <div class="backtest-spinner md" />
          <p class="mt-3 text-secondary-text text-sm">Loading results...</p>
        </div>
        <EmptyState
          v-else-if="results.length === 0"
          title="No Results"
          description="Run a backtest to evaluate historical analysis accuracy"
          class="backtest-empty-state border-dashed"
        >
          <template #icon>
            <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.5"
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
              />
            </svg>
          </template>
        </EmptyState>
        <div v-else class="animate-fade-in">
          <div class="backtest-table-toolbar">
            <div class="backtest-table-toolbar-meta">
              <span class="label-uppercase">{{
                isNextDayValidation ? 'Next-Day Validation' : 'Result Set'
              }}</span>
              <span class="text-xs text-secondary-text">
                {{ codeFilter.trim() ? `Filtered by ${codeFilter.trim()}` : 'All stocks' }}
                {{ evalDays ? ` · ${evalDays} day window` : '' }}
                {{ analysisDateFrom ? ` · from ${analysisDateFrom}` : '' }}
                {{ analysisDateTo ? ` · to ${analysisDateTo}` : '' }}
              </span>
            </div>
            <span class="backtest-table-scroll-hint">可横向滚动浏览完整结果</span>
          </div>
          <HorizontalScrollArea
            class="backtest-table-wrapper"
            viewport-class-name="backtest-table-scroll-viewport"
            aria-label="策略回测结果表格"
            hint-text="结果表格可横向滚动：拖动上方滚动条，或按住 Shift 滚动鼠标滚轮。"
          >
            <table class="backtest-table min-w-[840px] w-full text-sm">
              <thead class="backtest-table-head">
                <tr class="text-left">
                  <th class="backtest-table-head-cell">Stock</th>
                  <th class="backtest-table-head-cell">Analysis Date</th>
                  <th class="backtest-table-head-cell">AI Prediction</th>
                  <th class="backtest-table-head-cell">
                    {{ showNextDayActualColumns ? 'Actual' : 'Window Return' }}
                  </th>
                  <th class="backtest-table-head-cell">
                    {{ showNextDayActualColumns ? 'Accuracy' : 'Direction Match' }}
                  </th>
                  <th class="backtest-table-head-cell">Outcome</th>
                  <th class="backtest-table-head-cell">Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in results" :key="row.analysisHistoryId" class="backtest-table-row">
                  <td class="backtest-table-cell backtest-table-code">
                    <div class="flex flex-col">
                      <span>{{ row.code }}</span>
                      <span class="text-xs text-muted-text">{{ row.stockName || '--' }}</span>
                    </div>
                  </td>
                  <td class="backtest-table-cell text-secondary-text">{{ row.analysisDate || '--' }}</td>
                  <td class="backtest-table-cell max-w-[220px] text-foreground">
                    <template v-if="row.trendPrediction || row.operationAdvice">
                      <Tooltip
                        :content="[row.trendPrediction, row.operationAdvice].filter(Boolean).join(' / ')"
                        focusable
                      >
                        <div class="flex flex-col gap-1">
                          <span class="block truncate">{{ row.trendPrediction || '--' }}</span>
                          <span class="block truncate text-xs text-secondary-text">{{
                            row.operationAdvice || '--'
                          }}</span>
                        </div>
                      </Tooltip>
                    </template>
                    <template v-else>--</template>
                  </td>
                  <td class="backtest-table-cell">
                    <div class="flex items-center gap-2">
                      <Badge
                        v-if="row.actualMovement === 'up'"
                        variant="success"
                      >
                        UP
                      </Badge>
                      <Badge
                        v-else-if="row.actualMovement === 'down'"
                        variant="danger"
                      >
                        DOWN
                      </Badge>
                      <Badge
                        v-else-if="row.actualMovement === 'flat'"
                        variant="warning"
                      >
                        FLAT
                      </Badge>
                      <Badge v-else variant="default">--</Badge>
                      <span
                        :class="
                          row.actualReturnPct != null
                            ? row.actualReturnPct > 0
                              ? 'text-success'
                              : row.actualReturnPct < 0
                                ? 'text-danger'
                                : 'text-secondary-text'
                            : 'text-muted-text'
                        "
                      >
                        {{ pct(row.actualReturnPct) }}
                      </span>
                    </div>
                  </td>
                  <td class="backtest-table-cell">
                    <span class="flex items-center gap-2">
                      <span v-if="row.directionCorrect === true" class="backtest-status-chip backtest-status-chip-success" aria-label="yes">
                        <StatusDot tone="success" class="backtest-status-chip-dot" />
                        <Check class="h-3.5 w-3.5" />
                      </span>
                      <span v-else-if="row.directionCorrect === false" class="backtest-status-chip backtest-status-chip-danger" aria-label="no">
                        <StatusDot tone="danger" class="backtest-status-chip-dot" />
                        <X class="h-3.5 w-3.5" />
                      </span>
                      <span v-else class="backtest-status-chip backtest-status-chip-neutral" aria-label="unknown">
                        <StatusDot tone="neutral" class="backtest-status-chip-dot" />
                        <Minus class="h-3.5 w-3.5" />
                      </span>
                      <span class="text-muted-text">{{ row.directionExpected || '' }}</span>
                    </span>
                  </td>
                  <td class="backtest-table-cell">
                    <Badge
                      v-if="row.outcome === 'win'"
                      variant="success"
                      glow
                    >
                      WIN
                    </Badge>
                    <Badge
                      v-else-if="row.outcome === 'loss'"
                      variant="danger"
                      glow
                    >
                      LOSS
                    </Badge>
                    <Badge
                      v-else-if="row.outcome === 'neutral'"
                      variant="warning"
                    >
                      NEUTRAL
                    </Badge>
                    <Badge v-else-if="row.outcome" variant="default">{{ row.outcome }}</Badge>
                    <Badge v-else variant="default">--</Badge>
                  </td>
                  <td class="backtest-table-cell">
                    <Badge :variant="statusBadgeVariant(row.evalStatus)">
                      {{ statusBadgeLabel(row.evalStatus) }}
                    </Badge>
                  </td>
                </tr>
              </tbody>
            </table>
          </HorizontalScrollArea>
          <div class="mt-4">
            <Pagination
              :current-page="currentPage"
              :total-pages="totalPages"
              @page-change="handlePageChange"
            />
          </div>
          <p class="text-xs text-muted-text text-center mt-2">
            {{ totalResults }} result{{ totalResults !== 1 ? 's' : '' }} total · page {{ currentPage }} of
            {{ Math.max(totalPages, 1) }}
          </p>
        </div>
      </section>
    </main>
  </div>
</template>
