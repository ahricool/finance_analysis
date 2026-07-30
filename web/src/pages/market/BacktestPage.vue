<script setup lang="ts">
import { backtestsApi } from '@/api/backtests';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import BacktestEngineSelector from '@/components/backtest/BacktestEngineSelector.vue';
import BacktestPreflightPanel from '@/components/backtest/BacktestPreflightPanel.vue';
import BacktestRunTable from '@/components/backtest/BacktestRunTable.vue';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import AppCombobox from '@/components/app/AppCombobox.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
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
import { RouterLink } from 'vue-router';

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
const selectedStrategy = computed(() =>
  strategies.value.find((item) => item.key === form.strategyKey),
);
const marketOptions: BacktestMarket[] = ['US', 'CN', 'HK'];
const canCheck = computed(() =>
  Boolean(form.strategyKey && form.code && form.startDate && form.endDate),
);
const canStart = computed(() => preflightResult.value?.ready === true && !submitting.value);
const hasActiveRuns = computed(() =>
  runs.value.some((item) => item.status === 'pending' || item.status === 'processing'),
);

function marketSupported(market: BacktestMarket): boolean {
  return Boolean(
    selectedEngine.value?.supportedMarkets.includes(market) &&
      selectedStrategy.value?.supportedMarkets.includes(market),
  );
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
  form.parameters = Object.fromEntries(
    (strategy?.parameters ?? []).map((item) => [item.key, item.default]),
  );
}

async function loadSymbols(keyword = symbolKeyword.value) {
  symbols.value = marketSupported(form.market)
    ? await backtestsApi.symbols(form.market, form.engine, keyword.trim())
    : [];
  if (!symbols.value.some((item) => item.code === form.code))
    form.code = symbols.value[0]?.code ?? '';
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
    preflightResult.value = await backtestsApi.preflight({
      ...form,
      parameters: { ...form.parameters },
    });
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

watch(
  () => form.engine,
  async () => {
    invalidatePreflight();
    if (!engines.value.length) return;
    await loadStrategies();
    resetParameters();
    await refreshForMarket();
  },
);
watch(
  () => form.strategyKey,
  async () => {
    invalidatePreflight();
    resetParameters();
    if (strategies.value.length) await refreshForMarket();
  },
);
watch(
  () => form.market,
  async () => {
    invalidatePreflight();
    if (strategies.value.length) await refreshForMarket();
  },
);
watch(
  () => [
    form.code,
    form.startDate,
    form.endDate,
    form.initialCash,
    form.benchmarkCode,
    JSON.stringify(form.parameters),
  ],
  invalidatePreflight,
);

onMounted(async () => {
  loading.value = true;
  try {
    engines.value = (await backtestsApi.engines()).sort((a, b) => a.displayOrder - b.displayOrder);
    form.engine =
      engines.value.find((item) => item.isDefault && item.available)?.key ?? 'backtrader';
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
  <div class="min-w-0 space-y-6 py-4 sm:py-6">
    <PageHeader
      title="策略回测"
      description="配置回测、检查数据完备性，并跟踪历史运行结果。"
      section="市场"
    >
      <template #actions>
        <Button
          variant="outline"
          as-child
        >
          <RouterLink to="/tasks/runs">
            查看任务
          </RouterLink>
        </Button>
      </template>
    </PageHeader>

    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <Card :aria-busy="loading">
      <CardHeader>
        <CardTitle class="flex items-center gap-2">
          <FlaskConical class="size-5 text-primary" />回测配置
        </CardTitle>
        <CardDescription>先完成配置和数据预检，再提交后台回测任务。</CardDescription>
      </CardHeader>
      <CardContent
        v-if="loading"
        class="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      >
        <Skeleton
          v-for="index in 8"
          :key="index"
          class="h-16 w-full"
        />
      </CardContent>
      <CardContent
        v-else
        class="space-y-6"
      >
        <div class="space-y-3">
          <h3 class="text-sm font-medium">
            回测引擎
          </h3>
          <BacktestEngineSelector
            v-model="form.engine"
            :engines="engines"
          />
        </div>
        <Separator />
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <FieldSelect
            v-model="form.strategyKey"
            label="策略"
            :options="strategies.map((item) => ({ value: item.key, label: item.name }))"
          />
          <FieldSelect
            :model-value="form.market"
            label="市场"
            :options="
              marketOptions.map((item) => ({
                value: item,
                label: `${marketLabels[item]}${marketSupported(item) ? '' : '（不支持）'}`,
                disabled: !marketSupported(item),
              }))
            "
            @update:model-value="form.market = $event as BacktestMarket"
          />
          <div class="grid gap-2 md:col-span-2">
            <Label>标的搜索</Label>
            <div class="flex gap-2">
              <FieldInput
                v-model="symbolKeyword"
                class="min-w-0 flex-1"
                placeholder="代码或名称"
                @keyup.enter="loadSymbols()"
              /><Button
                variant="secondary"
                @click="loadSymbols()"
              >
                <Search class="h-4 w-4" />搜索
              </Button>
            </div>
          </div>
          <AppCombobox
            v-model="form.code"
            label="回测标的"
            :options="
              symbols.map((item) => ({ value: item.code, label: `${item.code} · ${item.name}` }))
            "
          />
          <AppDatePicker
            v-model="form.startDate"
            label="开始日期"
          />
          <AppDatePicker
            v-model="form.endDate"
            label="结束日期"
          />
          <div class="grid gap-2">
            <Label for="backtest-cash">初始资金</Label><Input
              id="backtest-cash"
              v-model="form.initialCash"
              type="number"
              min="1"
            />
          </div>
          <FieldSelect
            :model-value="form.benchmarkCode ?? ''"
            label="基准标的"
            :options="[
              { value: '', label: '不设置' },
              ...symbols.map((item) => ({ value: item.code, label: item.code })),
            ]"
            @update:model-value="form.benchmarkCode = $event || null"
          />
        </div>
        <div
          v-if="selectedStrategy"
          class="grid gap-4 sm:grid-cols-2"
        >
          <div
            v-for="parameter in selectedStrategy.parameters"
            :key="parameter.key"
            class="grid gap-2"
          >
            <Label :for="`backtest-param-${parameter.key}`">{{ parameter.name }}</Label><Input
              :id="`backtest-param-${parameter.key}`"
              v-model.number="form.parameters[parameter.key]"
              type="number"
              :min="parameter.minimum"
              :max="parameter.maximum"
            /><p class="text-xs text-muted-foreground">
              范围 {{ parameter.minimum }}–{{ parameter.maximum }}，默认 {{ parameter.default }}
            </p>
          </div>
        </div>
        <details class="rounded-xl border border-border/70 p-3 text-xs text-muted-foreground">
          <summary class="cursor-pointer font-medium text-foreground">
            高级设置（只读）
          </summary>
          <dl class="mt-3 grid gap-2 sm:grid-cols-2">
            <div>价格口径：未复权原始价格</div>
            <div>目标仓位：100% / 0%</div>
            <div>信号：收盘后计算</div>
            <div>成交：下一交易日开盘</div>
            <div>手续费：按市场默认模型</div>
            <div>市场规则版本：1.0.0</div>
          </dl>
        </details>
        <BacktestPreflightPanel
          v-if="preflightResult"
          :result="preflightResult"
        />
      </CardContent>
      <CardFooter
        v-if="!loading"
        class="justify-end gap-3 border-t pt-6"
      >
        <LoadingButton
          variant="secondary"
          :disabled="!canCheck"
          :loading="checking"
          @click="checkData"
        >
          检查数据
        </LoadingButton><LoadingButton
          :disabled="!canStart"
          :loading="submitting"
          @click="startBacktest"
        >
          开始回测
        </LoadingButton>
      </CardFooter>
    </Card>
    <BacktestRunTable
      :runs="runs"
      :loading="runsLoading"
      @reuse="reuse"
    />
  </div>
</template>
