<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { quantApi } from '@/api/quant';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Dialog from '@/components/common/Dialog.vue';
import type {
  ModelRunCreateAccepted,
  QuantDatasetSnapshot,
  QuantMarket,
  QuantModelDefinition,
} from '@/types/quant';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { computed, ref, watch } from 'vue';

type TrainableModelKey = 'cross_section_lgbm' | 'time_series_lgbm';

const props = defineProps<{
  isOpen: boolean;
  market: QuantMarket;
  initialDatasetId?: number | null;
}>();

const emit = defineEmits<{
  close: [];
  created: [result: ModelRunCreateAccepted];
  openDatasetBuilder: [market: QuantMarket];
}>();

const definitions = ref<QuantModelDefinition[]>([]);
const datasets = ref<QuantDatasetSnapshot[]>([]);
const selectedMarket = ref<QuantMarket>('US');
const selectedDatasetId = ref<number | null>(null);
const modelKey = ref<TrainableModelKey>('cross_section_lgbm');
const modelVersion = ref('');
const loadingOptions = ref(false);
const creatingRun = ref(false);
const error = ref<ParsedApiError | null>(null);
let requestVersion = 0;

const marketLocked = computed(() => props.initialDatasetId !== null && props.initialDatasetId !== undefined);
const readyDatasets = computed(() => datasets.value.filter((item) => (
  item.market === selectedMarket.value && item.status === 'ready' && Boolean(item.artifactUri)
)));
const selectedDataset = computed(() => (
  readyDatasets.value.find((item) => item.id === selectedDatasetId.value) ?? null
));
const trainableDefinitions = computed(() => definitions.value.filter((item) => (
  item.enabled && (item.key === 'cross_section_lgbm' || item.key === 'time_series_lgbm')
)));
const modelVersionValid = computed(() => /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(modelVersion.value.trim()));
const canCreateRun = computed(() => (
  Boolean(selectedDataset.value)
  && trainableDefinitions.value.some((item) => item.key === modelKey.value)
  && modelVersionValid.value
  && !loadingOptions.value
  && !creatingRun.value
));

function generateModelVersion(): void {
  const now = new Date();
  const timestamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    '-',
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
  ].join('');
  const model = modelKey.value === 'cross_section_lgbm' ? 'cross-section' : 'time-series';
  modelVersion.value = `${selectedMarket.value.toLowerCase()}-${model}-${timestamp}`;
}

function formatCount(value: number): string {
  return value.toLocaleString('zh-CN');
}

function priceModeLabel(value: string): string {
  if (value === 'forward_adjusted') return '前复权';
  if (value === 'raw') return '不复权';
  return value;
}

async function loadOptions(): Promise<void> {
  const version = ++requestVersion;
  loadingOptions.value = true;
  error.value = null;
  try {
    const [modelDefinitions, snapshots] = await Promise.all([
      quantApi.modelDefinitions(selectedMarket.value),
      quantApi.datasets(selectedMarket.value),
    ]);
    if (version !== requestVersion) return;
    definitions.value = modelDefinitions;
    datasets.value = snapshots;

    const preferredId = props.initialDatasetId ?? selectedDatasetId.value;
    selectedDatasetId.value = readyDatasets.value.some((item) => item.id === preferredId)
      ? preferredId
      : readyDatasets.value[0]?.id ?? null;

    if (!trainableDefinitions.value.some((item) => item.key === modelKey.value)) {
      const first = trainableDefinitions.value[0]?.key;
      if (first === 'cross_section_lgbm' || first === 'time_series_lgbm') modelKey.value = first;
    }
  } catch (err) {
    if (version === requestVersion) error.value = getParsedApiError(err);
  } finally {
    if (version === requestVersion) loadingOptions.value = false;
  }
}

function requestClose(): void {
  if (!creatingRun.value) emit('close');
}

function openDatasetBuilder(): void {
  emit('openDatasetBuilder', selectedMarket.value);
}

async function createRun(): Promise<void> {
  if (!selectedDataset.value || !canCreateRun.value) return;
  error.value = null;
  creatingRun.value = true;
  try {
    const result = await quantApi.createModelRun({
      market: selectedMarket.value,
      modelKey: modelKey.value,
      modelVersion: modelVersion.value.trim(),
      datasetSnapshotId: selectedDataset.value.id,
    });
    emit('created', result);
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    creatingRun.value = false;
  }
}

watch(() => props.isOpen, (isOpen) => {
  if (!isOpen) {
    requestVersion += 1;
    return;
  }
  const marketChanged = selectedMarket.value !== props.market;
  selectedMarket.value = props.market;
  selectedDatasetId.value = props.initialDatasetId ?? null;
  modelKey.value = 'cross_section_lgbm';
  error.value = null;
  generateModelVersion();
  if (!marketChanged) void loadOptions();
});

watch(selectedMarket, (current, previous) => {
  if (!props.isOpen || current === previous) return;
  selectedDatasetId.value = null;
  generateModelVersion();
  void loadOptions();
});

watch(modelKey, () => {
  if (props.isOpen) generateModelVersion();
});
</script>

<template>
  <Dialog
    :is-open="isOpen"
    title="创建训练任务"
    description="选择一个已就绪的数据集快照，使用后端默认 Walk-forward 配置启动训练。"
    width="max-w-3xl"
    @close="requestClose"
  >
    <form class="space-y-5" data-testid="training-run-form" @submit.prevent="createRun">
      <ApiErrorAlert v-if="error" :error="error" @dismiss="error = null" />

      <fieldset>
        <legend class="mb-2 text-xs font-medium text-muted-text">市场</legend>
        <div v-if="marketLocked" class="rounded-xl border border-border bg-elevated px-3 py-2.5 text-sm text-foreground">
          {{ selectedMarket === 'US' ? '美股 · US' : 'A股 · CN' }}
          <span class="ml-2 text-xs text-muted-text">由所选数据集确定</span>
        </div>
        <div v-else class="grid grid-cols-2 gap-2" role="radiogroup" aria-label="训练市场">
          <label
            v-for="option in [{ value: 'US', label: '美股 · US' }, { value: 'CN', label: 'A股 · CN' }]"
            :key="option.value"
            class="cursor-pointer rounded-xl border p-3 text-sm transition-colors"
            :class="selectedMarket === option.value ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border bg-background text-secondary-text hover:bg-hover'"
          >
            <input v-model="selectedMarket" class="sr-only" type="radio" :value="option.value">
            <span class="font-medium">{{ option.label }}</span>
          </label>
        </div>
      </fieldset>

      <section>
        <div class="mb-2 flex items-center justify-between gap-3">
          <h3 class="text-sm font-semibold text-foreground">数据集快照</h3>
          <Button variant="ghost" size="sm" :is-loading="loadingOptions" loading-text="刷新中" @click="loadOptions">
            刷新
          </Button>
        </div>

        <div v-if="loadingOptions" class="rounded-xl border border-border bg-background px-4 py-8 text-center text-sm text-muted-text">
          正在加载可训练数据集...
        </div>
        <div
          v-else-if="readyDatasets.length"
          class="max-h-64 space-y-2 overflow-y-auto pr-1"
          data-testid="training-dataset-options"
        >
          <label
            v-for="item in readyDatasets"
            :key="item.id"
            class="block cursor-pointer rounded-xl border p-3 transition-colors"
            :class="selectedDatasetId === item.id ? 'border-primary/50 bg-primary/10' : 'border-border bg-background hover:bg-hover'"
          >
            <div class="flex items-start gap-3">
              <input v-model.number="selectedDatasetId" class="mt-1 h-4 w-4 accent-primary" type="radio" :value="item.id">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span class="font-mono text-sm font-semibold text-foreground">#{{ item.id }}</span>
                  <span class="text-sm text-foreground">{{ item.dateFrom }} → {{ item.dateTo }}</span>
                </div>
                <p class="mt-1 text-xs leading-5 text-secondary-text">
                  {{ formatCount(item.symbolCount) }} 只股票 · {{ formatCount(item.rowCount) }} 行
                  · {{ priceModeLabel(item.priceMode) }} · {{ item.featureVersion }}
                </p>
                <p class="mt-0.5 text-xs text-muted-text">
                  创建于 {{ formatDateTimeInDisplayTimezone(item.createdAt) }}
                </p>
              </div>
            </div>
          </label>
        </div>
        <div
          v-else
          class="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-center"
          data-testid="training-dataset-empty"
        >
          <p class="text-sm font-medium text-foreground">当前市场没有已就绪的数据集。</p>
          <p class="mt-1 text-xs text-muted-text">请先前往数据集页面构建数据集。</p>
          <Button class="mt-4" variant="secondary" size="sm" @click="openDatasetBuilder">
            前往构建数据集
          </Button>
        </div>
      </section>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="text-sm">
          <span class="mb-1.5 block text-xs font-medium text-muted-text">模型类型</span>
          <select
            v-model="modelKey"
            data-testid="training-model-select"
            class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
            :disabled="loadingOptions || trainableDefinitions.length === 0"
          >
            <option v-for="item in trainableDefinitions" :key="item.key" :value="item.key">
              {{ item.name }} · {{ item.key }}
            </option>
          </select>
        </label>
        <label class="text-sm">
          <span class="mb-1.5 block text-xs font-medium text-muted-text">模型版本</span>
          <input
            v-model="modelVersion"
            data-testid="training-model-version"
            required
            maxlength="96"
            pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
            class="h-10 w-full rounded-xl border border-border bg-card px-3 font-mono text-sm text-foreground"
          >
          <span v-if="modelVersion && !modelVersionValid" class="mt-1 block text-xs text-danger">
            只能包含字母、数字、点、下划线和连字符，且必须以字母或数字开头。
          </span>
        </label>
      </div>

      <section class="rounded-xl border border-border bg-background p-4" data-testid="training-config-summary">
        <div class="flex items-center justify-between gap-3">
          <h3 class="text-sm font-semibold text-foreground">训练配置摘要</h3>
          <span class="text-xs text-muted-text">后端默认配置</span>
        </div>
        <dl class="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div class="flex justify-between gap-3"><dt class="text-muted-text">训练方式</dt><dd>Walk-forward</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">训练窗口</dt><dd>3 年</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">验证窗口</dt><dd>3 个月</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">测试窗口</dt><dd>3 个月</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">重训频率</dt><dd>3 个月</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">预测周期</dt><dd>5 个交易日</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">Embargo</dt><dd>2 个交易日</dd></div>
          <div class="flex justify-between gap-3"><dt class="text-muted-text">特征</dt><dd class="text-right">Alpha158 + 自定义扩展特征</dd></div>
          <div class="flex justify-between gap-3 sm:col-span-2"><dt class="text-muted-text">标签</dt><dd class="text-right">T+1 开盘 → T+5 收盘的超额收益</dd></div>
        </dl>
      </section>

      <div class="flex flex-col-reverse gap-2 border-t border-border/60 pt-4 sm:flex-row sm:justify-end">
        <Button variant="ghost" :disabled="creatingRun" @click="requestClose">取消</Button>
        <Button
          type="submit"
          data-testid="create-training-run"
          :disabled="!canCreateRun"
          :is-loading="creatingRun"
          loading-text="创建中"
        >
          创建并启动训练
        </Button>
      </div>
    </form>
  </Dialog>
</template>
