<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Drawer from '@/components/common/Drawer.vue';
import type {
  QuantDatasetSnapshot,
  QuantMarket,
  QuantModelDefinition,
} from '@/types/quant';

const props = defineProps<{
  isOpen: boolean;
  market: QuantMarket;
}>();

const emit = defineEmits<{
  close: [];
  created: [runId: number];
}>();

const definitions = ref<QuantModelDefinition[]>([]);
const datasets = ref<QuantDatasetSnapshot[]>([]);
const selectedDatasetId = ref<number | null>(null);
const modelKey = ref<'cross_section_lgbm' | 'time_series_lgbm'>('cross_section_lgbm');
const modelVersion = ref('');
const dateFrom = ref('');
const dateTo = ref('');
const loadingOptions = ref(false);
const buildingDataset = ref(false);
const creatingRun = ref(false);
const error = ref<ParsedApiError | null>(null);
const successMessage = ref('');
const datasetTaskId = ref('');
let requestVersion = 0;

const readyDatasets = computed(() => datasets.value.filter((item) => item.status === 'ready' && item.artifactUri));
const selectedDataset = computed(() => (
  readyDatasets.value.find((item) => item.id === selectedDatasetId.value) ?? null
));
const canCreateRun = computed(() => (
  Boolean(selectedDataset.value)
  && Boolean(modelVersion.value.trim())
  && !loadingOptions.value
  && !creatingRun.value
));

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function resetDates(): void {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 5);
  dateFrom.value = formatDateInput(start);
  dateTo.value = formatDateInput(end);
}

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
  modelVersion.value = `${props.market.toLowerCase()}-${model}-${timestamp}`;
}

async function loadOptions(): Promise<void> {
  const version = ++requestVersion;
  loadingOptions.value = true;
  error.value = null;
  try {
    const [modelDefinitions, snapshots] = await Promise.all([
      quantApi.modelDefinitions(props.market),
      quantApi.datasets(props.market),
    ]);
    if (version !== requestVersion) return;
    definitions.value = modelDefinitions;
    datasets.value = snapshots;
    const currentStillReady = readyDatasets.value.some((item) => item.id === selectedDatasetId.value);
    if (!currentStillReady) selectedDatasetId.value = readyDatasets.value[0]?.id ?? null;
    if (!definitions.value.some((item) => item.key === modelKey.value)) {
      const firstModelKey = definitions.value[0]?.key;
      modelKey.value = firstModelKey === 'time_series_lgbm' ? firstModelKey : 'cross_section_lgbm';
    }
  } catch (err) {
    if (version === requestVersion) error.value = getParsedApiError(err);
  } finally {
    if (version === requestVersion) loadingOptions.value = false;
  }
}

async function buildDataset(): Promise<void> {
  error.value = null;
  successMessage.value = '';
  datasetTaskId.value = '';
  if (!dateFrom.value || !dateTo.value || dateFrom.value > dateTo.value) {
    error.value = {
      title: '日期范围无效',
      message: '请确认开始日期不晚于结束日期。',
      rawMessage: 'Invalid dataset date range',
      category: 'missing_params',
    };
    return;
  }
  buildingDataset.value = true;
  try {
    const result = await quantApi.buildDataset(props.market, dateFrom.value, dateTo.value);
    datasetTaskId.value = result.taskId;
    successMessage.value = '数据集构建任务已提交。任务完成后刷新数据集列表，再创建模型训练任务。';
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    buildingDataset.value = false;
  }
}

async function createRun(): Promise<void> {
  if (!selectedDataset.value || !canCreateRun.value) return;
  error.value = null;
  successMessage.value = '';
  creatingRun.value = true;
  try {
    const result = await quantApi.createModelRun({
      market: props.market,
      modelKey: modelKey.value,
      modelVersion: modelVersion.value.trim(),
      datasetSnapshotId: selectedDataset.value.id,
    });
    emit('created', result.modelRunId);
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    creatingRun.value = false;
  }
}

watch(
  () => [props.isOpen, props.market] as const,
  ([isOpen], previous) => {
    if (!isOpen) return;
    const marketChanged = previous?.[1] !== props.market;
    if (marketChanged || !dateFrom.value) resetDates();
    successMessage.value = '';
    datasetTaskId.value = '';
    selectedDatasetId.value = null;
    generateModelVersion();
    void loadOptions();
  },
  { immediate: true },
);

watch(modelKey, () => {
  if (props.isOpen) generateModelVersion();
});
</script>

<template>
  <Drawer
    :is-open="isOpen"
    title="创建量化训练任务"
    width="max-w-3xl"
    @close="emit('close')"
  >
    <div class="space-y-5" data-testid="quant-training-drawer">
      <p class="text-sm leading-6 text-secondary-text">
        训练使用已固化的数据集快照异步执行。训练完成后模型进入 candidate，仍需管理员审核并发布为 production。
      </p>

      <ApiErrorAlert v-if="error" :error="error" />
      <div
        v-if="successMessage"
        class="rounded-xl border border-success/30 bg-success/10 p-3 text-sm text-success"
      >
        {{ successMessage }}
        <RouterLink
          v-if="datasetTaskId"
          to="/tasks/runs"
          class="ml-1 underline"
        >
          查看任务 {{ datasetTaskId }}
        </RouterLink>
      </div>

      <section class="rounded-2xl border border-border bg-background/50 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-primary">步骤 1</p>
            <h3 class="mt-1 font-semibold text-foreground">选择已就绪数据集</h3>
            <p class="mt-1 text-xs text-muted-text">数据集固定训练范围和当时可用的行情、基准及特征。</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            :is-loading="loadingOptions"
            loading-text="刷新中"
            @click="loadOptions"
          >
            刷新数据集
          </Button>
        </div>

        <label class="mt-4 block text-sm">
          <span class="mb-1.5 block text-xs text-muted-text">数据集快照</span>
          <select
            v-model.number="selectedDatasetId"
            data-testid="training-dataset-select"
            class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
            :disabled="loadingOptions || readyDatasets.length === 0"
          >
            <option :value="null" disabled>
              {{ loadingOptions ? '加载中...' : '请选择已就绪数据集' }}
            </option>
            <option v-for="item in readyDatasets" :key="item.id" :value="item.id">
              #{{ item.id }} · {{ item.dateFrom }} → {{ item.dateTo }} · {{ item.symbolCount }} 只股票
            </option>
          </select>
        </label>

        <div
          v-if="!loadingOptions && readyDatasets.length === 0"
          class="mt-3 rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning"
        >
          当前市场没有可训练的数据集，请先提交下方构建任务。
        </div>

        <form
          class="mt-4 grid gap-3 border-t border-border/60 pt-4 sm:grid-cols-[1fr_1fr_auto]"
          data-testid="dataset-build-form"
          @submit.prevent="buildDataset"
        >
          <label class="text-xs text-muted-text">
            开始日期
            <input
              v-model="dateFrom"
              data-testid="dataset-date-from"
              type="date"
              required
              class="mt-1.5 h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
            >
          </label>
          <label class="text-xs text-muted-text">
            结束日期
            <input
              v-model="dateTo"
              data-testid="dataset-date-to"
              type="date"
              required
              class="mt-1.5 h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
            >
          </label>
          <Button
            class="self-end"
            variant="secondary"
            type="submit"
            :is-loading="buildingDataset"
            loading-text="提交中"
          >
            构建新数据集
          </Button>
        </form>
      </section>

      <form
        class="rounded-2xl border border-border bg-background/50 p-4"
        data-testid="training-run-form"
        @submit.prevent="createRun"
      >
        <p class="text-xs font-semibold uppercase tracking-wide text-primary">步骤 2</p>
        <h3 class="mt-1 font-semibold text-foreground">创建模型训练运行</h3>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label class="text-sm">
            <span class="mb-1.5 block text-xs text-muted-text">模型</span>
            <select
              v-model="modelKey"
              data-testid="training-model-select"
              class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
              :disabled="loadingOptions || definitions.length === 0"
            >
              <option v-for="item in definitions" :key="item.key" :value="item.key">
                {{ item.name }}
              </option>
            </select>
          </label>
          <label class="text-sm">
            <span class="mb-1.5 block text-xs text-muted-text">模型版本</span>
            <input
              v-model="modelVersion"
              data-testid="training-model-version"
              required
              maxlength="96"
              pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
              class="h-10 w-full rounded-xl border border-border bg-card px-3 font-mono text-sm text-foreground"
            >
          </label>
        </div>
        <p class="mt-3 text-xs leading-5 text-muted-text">
          Daily 流水线需要分别训练并发布 cross_section_lgbm 和 time_series_lgbm；可使用同一个数据集分别创建两次运行。
        </p>
        <div class="mt-5 flex justify-end gap-3">
          <Button variant="ghost" @click="emit('close')">取消</Button>
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
    </div>
  </Drawer>
</template>
