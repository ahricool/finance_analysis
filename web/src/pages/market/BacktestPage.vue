<script setup lang="ts">
import { backtestsApi } from '@/api/backtests';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import BacktestEngineSelector from '@/components/backtest/BacktestEngineSelector.vue';
import BacktestPreflightPanel from '@/components/backtest/BacktestPreflightPanel.vue';
import BacktestRunTable from '@/components/backtest/BacktestRunTable.vue';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import type {
  BacktestConfig,
  BacktestEngine,
  BacktestMarket,
  BacktestPreflight,
  BacktestRun,
  BacktestStrategy,
  BacktestSymbol,
} from '@/types/backtests';
import { marketLabels } from '@/utils/backtests';
import { FlaskConical, Search } from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';

const engines = ref<BacktestEngine[]>([]);
const strategies = ref<BacktestStrategy[]>([]);
const symbols = ref<BacktestSymbol[]>([]);
const runs = ref<BacktestRun[]>([]);
const preflightResult = ref<BacktestPreflight | null>(null);
const loading = ref(false);
const checking = ref(false);
const submitting = ref(false);
const runsLoading = ref(false);
const error = ref<ParsedApiError | null>(null);
const symbolKeyword = ref('');
let pollTimer: ReturnType<typeof setInterval> | null = null;

const today = new Date();
const yearAgo = new Date(today);
yearAgo.setFullYear(today.getFullYear() - 1);
const isoDate = (value: Date) => value.toISOString().slice(0, 10);

const form = reactive<BacktestConfig>({
  engine: 'backtrader',
  strategyKey: '',
  market: 'US',
  code: '',
  startDate: isoDate(yearAgo),
  endDate: isoDate(today),
  initialCash: 100000,
  benchmarkCode: null,
  parameters: {},
});

const selectedEngine = computed(() => engines.value.find((item) => item.key === form.engine));
const selectedStrategy = computed(() => strategies.value.find((item) => item.key === form.strategyKey));
const marketOptions: BacktestMarket[] = ['US', 'CN', 'HK'];
const canCheck = computed(() => Boolean(form.strategyKey && form.code && form.startDate && form.endDate));
const canStart = computed(() => preflightResult.value?.ready === true && !submitting.value);
const hasActiveRuns = computed(() => runs.value.some((item) => item.status === 'pending' || item.status === 'processing'));

function marketSupported(market: BacktestMarket): boolean {
  return Boolean(selectedEngine.value?.supportedMarkets.includes(market)
    && selectedStrategy.value?.supportedMarkets.includes(market));
}

function invalidatePreflight() {
  preflightResult.value = null;
}

async function loadStrategies() {
  strategies.value = await backtestsApi.strategies(form.engine);
  if (!strategies.value.some((item) => item.key === form.strategyKey)) {
    form.strategyKey = strategies.value[0]?.key ?? '';
  }
}

function resetParameters() {
  const strategy = selectedStrategy.value;
  form.parameters = Object.fromEntries((strategy?.parameters ?? []).map((item) => [item.key, item.default]));
}

async function loadSymbols(keyword = symbolKeyword.value) {
  symbols.value = marketSupported(form.market)
    ? await backtestsApi.symbols(form.market, form.engine, keyword.trim())
    : [];
  if (!symbols.value.some((item) => item.code === form.code)) form.code = symbols.value[0]?.code ?? '';
}

async function setDefaultBenchmark() {
  const defaults: Record<BacktestMarket, string> = { US: 'SPY.US', CN: '000300.SH', HK: '2800.HK' };
  const matches = await backtestsApi.symbols(form.market, form.engine, defaults[form.market]);
  form.benchmarkCode = matches.find((item) => item.code === defaults[form.market])?.code ?? null;
}

async function refreshForMarket() {
  if (!marketSupported(form.market)) {
    const fallback = marketOptions.find(marketSupported);
    if (fallback) form.market = fallback;
  }
  await Promise.all([loadSymbols(), setDefaultBenchmark()]);
}

async function loadRuns() {
  runsLoading.value = true;
  try {
    runs.value = (await backtestsApi.runs()).items;
    updatePolling();
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    runsLoading.value = false;
  }
}

function updatePolling() {
  if (hasActiveRuns.value && !pollTimer) pollTimer = setInterval(() => void loadRuns(), 5000);
  if (!hasActiveRuns.value && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function checkData() {
  checking.value = true;
  error.value = null;
  try {
    preflightResult.value = await backtestsApi.preflight({ ...form, parameters: { ...form.parameters } });
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    checking.value = false;
  }
}

async function startBacktest() {
  if (!canStart.value) return;
  submitting.value = true;
  error.value = null;
  try {
    await backtestsApi.create({ ...form, parameters: { ...form.parameters } });
    invalidatePreflight();
    await loadRuns();
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    submitting.value = false;
  }
}

async function reuse(run: BacktestRun) {
  Object.assign(form, {
    engine: run.engine,
    strategyKey: run.strategyKey,
    market: run.market,
    code: run.code,
    startDate: run.startDate,
    endDate: run.endDate,
    initialCash: run.initialCash,
    benchmarkCode: run.benchmarkCode,
    parameters: { ...run.parameters },
  });
  await loadStrategies();
  await loadSymbols(run.code);
  invalidatePreflight();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

watch(() => form.engine, async () => {
  invalidatePreflight();
  if (!engines.value.length) return;
  await loadStrategies();
  resetParameters();
  await refreshForMarket();
});
watch(() => form.strategyKey, async () => {
  invalidatePreflight();
  resetParameters();
  if (strategies.value.length) await refreshForMarket();
});
watch(() => form.market, async () => {
  invalidatePreflight();
  if (strategies.value.length) await refreshForMarket();
});
watch(
  () => [form.code, form.startDate, form.endDate, form.initialCash, form.benchmarkCode, JSON.stringify(form.parameters)],
  invalidatePreflight,
);

onMounted(async () => {
  loading.value = true;
  try {
    engines.value = (await backtestsApi.engines()).sort((a, b) => a.displayOrder - b.displayOrder);
    form.engine = engines.value.find((item) => item.isDefault && item.available)?.key ?? 'backtrader';
    await loadStrategies();
    resetParameters();
    await refreshForMarket();
    await loadRuns();
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
});
</script>

<template>
  <div class="min-w-0 space-y-5">
    <header class="flex items-start gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-primary-foreground">
        <FlaskConical class="h-5 w-5" />
      </div>
      <div>
        <h2 class="text-lg font-semibold text-foreground">
          策略回测
        </h2><p class="mt-1 text-xs text-secondary-text">
          选择回测引擎、策略、标的和时间范围，使用数据库历史行情执行日线策略回测。
        </p>
      </div>
    </header>

    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <section
      class="space-y-5 rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card"
      :aria-busy="loading"
    >
      <div>
        <h3 class="mb-3 text-sm font-semibold text-foreground">
          1. 回测引擎
        </h3><BacktestEngineSelector
          v-model="form.engine"
          :engines="engines"
        />
      </div>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">策略</span><select
          v-model="form.strategyKey"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ><option
          v-for="item in strategies"
          :key="item.key"
          :value="item.key"
        >{{ item.name }}</option></select></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">市场</span><select
          v-model="form.market"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ><option
          v-for="item in marketOptions"
          :key="item"
          :value="item"
          :disabled="!marketSupported(item)"
        >{{ marketLabels[item] }}{{ marketSupported(item) ? '' : '（不支持）' }}</option></select></label>
        <label class="text-xs text-muted-text md:col-span-2"><span class="mb-1.5 block">标的搜索</span><div class="flex gap-2"><input
          v-model="symbolKeyword"
          class="input-surface h-11 min-w-0 flex-1 rounded-xl border bg-transparent px-3 text-sm text-foreground"
          placeholder="代码或名称"
          @keyup.enter="loadSymbols()"
        ><Button
          variant="secondary"
          @click="loadSymbols()"
        ><Search class="h-4 w-4" />搜索</Button></div></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">回测标的</span><select
          v-model="form.code"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ><option
          v-for="item in symbols"
          :key="item.id"
          :value="item.code"
        >{{ item.code }} · {{ item.name }}</option></select></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">开始日期</span><input
          v-model="form.startDate"
          type="date"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">结束日期</span><input
          v-model="form.endDate"
          type="date"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">初始资金</span><input
          v-model.number="form.initialCash"
          type="number"
          min="1"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ></label>
        <label class="text-xs text-muted-text"><span class="mb-1.5 block">基准标的</span><select
          v-model="form.benchmarkCode"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ><option :value="null">不设置</option><option
          v-for="item in symbols"
          :key="item.id"
          :value="item.code"
        >{{ item.code }}</option></select></label>
      </div>
      <div
        v-if="selectedStrategy"
        class="grid gap-4 sm:grid-cols-2"
      >
        <label
          v-for="parameter in selectedStrategy.parameters"
          :key="parameter.key"
          class="text-xs text-muted-text"
        ><span class="mb-1.5 block">{{ parameter.name }}</span><input
          v-model.number="form.parameters[parameter.key]"
          type="number"
          :min="parameter.minimum"
          :max="parameter.maximum"
          class="input-surface h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground"
        ><span class="mt-1 block">范围 {{ parameter.minimum }}–{{ parameter.maximum }}，默认 {{ parameter.default }}</span></label>
      </div>
      <details class="rounded-xl border border-border/70 p-3 text-xs text-secondary-text">
        <summary class="cursor-pointer font-medium text-foreground">
          高级设置（只读）
        </summary><dl class="mt-3 grid gap-2 sm:grid-cols-2">
          <div>价格口径：未复权原始价格</div><div>目标仓位：100% / 0%</div><div>信号：收盘后计算</div><div>成交：下一交易日开盘</div><div>手续费：按市场默认模型</div><div>市场规则版本：1.0.0</div>
        </dl>
      </details>
      <BacktestPreflightPanel
        v-if="preflightResult"
        :result="preflightResult"
      />
      <div class="flex justify-end gap-3">
        <Button
          variant="secondary"
          :disabled="!canCheck"
          :is-loading="checking"
          @click="checkData"
        >
          检查数据
        </Button><Button
          :disabled="!canStart"
          :is-loading="submitting"
          @click="startBacktest"
        >
          开始回测
        </Button>
      </div>
    </section>
    <BacktestRunTable
      :runs="runs"
      :loading="runsLoading"
      @reuse="reuse"
    />
  </div>
</template>
