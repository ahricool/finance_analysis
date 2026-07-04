<script setup lang="ts">
import { backtestsApi } from '@/api/backtests';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import BacktestEquityChart from '@/components/backtest/BacktestEquityChart.vue';
import BacktestSummaryCards from '@/components/backtest/BacktestSummaryCards.vue';
import BacktestTradeTable from '@/components/backtest/BacktestTradeTable.vue';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import type { BacktestEquity, BacktestRun, BacktestTrade } from '@/types/backtests';
import { engineLabels, formatMoney, marketLabels, statusLabels } from '@/utils/backtests';
import { ArrowLeft, TriangleAlert } from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

const route = useRoute();
const runId = Number(route.params.runId);
const run = ref<BacktestRun | null>(null);
const trades = ref<BacktestTrade[]>([]);
const equity = ref<BacktestEquity[]>([]);
const loading = ref(true);
const error = ref<ParsedApiError | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

const duration = computed(() => {
  if (!run.value?.startedAt || !run.value.finishedAt) return '—';
  const seconds = Math.max(0, (Date.parse(run.value.finishedAt) - Date.parse(run.value.startedAt)) / 1000);
  return seconds < 60 ? `${seconds.toFixed(1)} 秒` : `${(seconds / 60).toFixed(1)} 分钟`;
});

async function load() {
  try {
    run.value = await backtestsApi.run(runId);
    if (run.value.status === 'completed') [trades.value, equity.value] = await Promise.all([backtestsApi.trades(runId), backtestsApi.equity(runId)]);
    if (run.value.status === 'pending' || run.value.status === 'processing') {
      if (!timer) timer = setInterval(() => void load(), 5000);
    } else if (timer) {
      clearInterval(timer); timer = null;
    }
  } catch (err) { error.value = getParsedApiError(err); }
  finally { loading.value = false; }
}

onMounted(load);
onBeforeUnmount(() => { if (timer) clearInterval(timer); timer = null; });
</script>

<template>
  <div class="min-w-0 space-y-5">
    <RouterLink
      to="/market/backtests"
      class="inline-flex items-center gap-2 text-sm text-secondary-text hover:text-primary"
    >
      <ArrowLeft class="h-4 w-4" />返回策略回测
    </RouterLink>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="p-10 text-center text-muted-text"
    >
      加载中...
    </div>
    <template v-else-if="run">
      <section class="rounded-2xl border border-primary/30 bg-card/94 p-5 shadow-soft-card">
        <div class="flex flex-wrap items-center gap-3">
          <h2 class="text-xl font-semibold text-foreground">
            回测 #{{ run.id }}
          </h2><Badge
            :variant="run.engine === 'backtrader' ? 'success' : 'info'"
            size="md"
          >
            {{ engineLabels[run.engine] }} · v{{ run.engineVersion || '未知' }}
          </Badge><Badge variant="default">
            {{ statusLabels[run.status] }} {{ run.status === 'processing' ? `${run.progress}%` : '' }}
          </Badge>
        </div>
        <dl class="mt-5 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt class="text-muted-text">
              策略
            </dt><dd>{{ run.strategyName }} · v{{ run.strategyVersion }}</dd>
          </div><div>
            <dt class="text-muted-text">
              市场 / 标的
            </dt><dd>{{ marketLabels[run.market] }} · {{ run.code }}</dd>
          </div><div>
            <dt class="text-muted-text">
              日期范围
            </dt><dd>{{ run.startDate }} — {{ run.endDate }}</dd>
          </div><div>
            <dt class="text-muted-text">
              初始资金
            </dt><dd>{{ formatMoney(run.initialCash) }}</dd>
          </div><div>
            <dt class="text-muted-text">
              耗时
            </dt><dd>{{ duration }}</dd>
          </div><div>
            <dt class="text-muted-text">
              Task ID
            </dt><dd class="break-all">
              {{ run.taskId || '—' }}
            </dd>
          </div><div>
            <dt class="text-muted-text">
              基准
            </dt><dd>{{ run.benchmarkCode || '未设置' }}</dd>
          </div><div>
            <dt class="text-muted-text">
              参数
            </dt><dd>{{ JSON.stringify(run.parameters) }}</dd>
          </div>
        </dl>
        <p
          v-if="run.error"
          class="mt-4 rounded-xl bg-danger/10 p-3 text-xs text-danger"
        >
          {{ run.error }}
        </p>
      </section>
      <div
        v-if="run.priceMode === 'raw'"
        class="flex gap-2 rounded-2xl border border-warning/30 bg-warning/8 p-4 text-sm text-warning"
      >
        <TriangleAlert class="h-5 w-5 shrink-0" /><span>当前结果使用未复权价格，拆股、分红或除权可能影响策略信号和收益。</span>
      </div>
      <BacktestSummaryCards :summary="run.summary" />
      <BacktestEquityChart
        :equity="equity"
        :trades="trades"
      />
      <BacktestTradeTable :trades="trades" />
      <details class="rounded-2xl border border-border/70 bg-card/94 p-4 text-xs">
        <summary class="cursor-pointer font-semibold text-foreground">
          运行配置
        </summary><div class="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <h4 class="mb-2 text-muted-text">
              Engine config
            </h4><pre class="overflow-auto rounded-xl bg-elevated/60 p-3">{{ JSON.stringify(run.engineConfig, null, 2) }}</pre>
          </div><div>
            <h4 class="mb-2 text-muted-text">
              策略 / 市场规则
            </h4><pre class="overflow-auto rounded-xl bg-elevated/60 p-3">{{ JSON.stringify({ parameters: run.parameters, marketRuleVersion: run.marketRuleVersion, priceMode: run.priceMode }, null, 2) }}</pre>
          </div>
        </div><ul
          v-if="run.warnings.length"
          class="mt-3 list-disc pl-5 text-warning"
        >
          <li
            v-for="item in run.warnings"
            :key="item"
          >
            {{ item }}
          </li>
        </ul>
      </details>
    </template>
  </div>
</template>
