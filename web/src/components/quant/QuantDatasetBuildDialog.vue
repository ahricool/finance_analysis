<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { quantApi } from '@/api/quant';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Dialog from '@/components/common/Dialog.vue';
import type { DatasetBuildAccepted, QuantMarket } from '@/types/quant';
import { computed, ref, watch } from 'vue';

const props = defineProps<{
  isOpen: boolean;
  market: QuantMarket;
}>();

const emit = defineEmits<{
  close: [];
  submitted: [result: DatasetBuildAccepted];
}>();

const selectedMarket = ref<QuantMarket>('US');
const dateFrom = ref('');
const dateTo = ref('');
const submitting = ref(false);
const error = ref<ParsedApiError | null>(null);

const universe = computed(() => selectedMarket.value === 'US'
  ? { name: 'S&P 500', key: 'us_sp500' }
  : { name: '沪深300', key: 'cn_csi300' });
const dateRangeValid = computed(() => Boolean(dateFrom.value && dateTo.value && dateFrom.value <= dateTo.value));

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function resetForm(): void {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 5);
  selectedMarket.value = props.market;
  dateFrom.value = formatDateInput(start);
  dateTo.value = formatDateInput(end);
  error.value = null;
}

function requestClose(): void {
  if (!submitting.value) emit('close');
}

async function submit(): Promise<void> {
  error.value = null;
  if (!dateRangeValid.value) {
    error.value = {
      title: '日期范围无效',
      message: '请确认开始日期不晚于结束日期。',
      rawMessage: 'Invalid dataset date range',
      category: 'missing_params',
    };
    return;
  }

  submitting.value = true;
  try {
    const result = await quantApi.buildDataset(selectedMarket.value, dateFrom.value, dateTo.value);
    emit('submitted', result);
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    submitting.value = false;
  }
}

watch(() => props.isOpen, (isOpen) => {
  if (isOpen) resetForm();
});
</script>

<template>
  <Dialog
    :is-open="isOpen"
    title="构建数据集"
    description="提交后将在后台构建数据集。任务完成且状态变为 ready 后，才能用于模型训练。"
    width="max-w-2xl"
    @close="requestClose"
  >
    <form class="space-y-5" data-testid="dataset-build-form" @submit.prevent="submit">
      <ApiErrorAlert v-if="error" :error="error" @dismiss="error = null" />

      <fieldset>
        <legend class="mb-2 text-xs font-medium text-muted-text">市场</legend>
        <div class="grid grid-cols-2 gap-2" role="radiogroup" aria-label="数据集市场">
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

      <label class="block text-sm">
        <span class="mb-1.5 block text-xs font-medium text-muted-text">Universe（固定）</span>
        <input
          :value="`${universe.name} / ${universe.key}`"
          readonly
          data-testid="dataset-universe"
          class="h-10 w-full rounded-xl border border-border bg-elevated px-3 text-sm text-secondary-text"
        >
      </label>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="text-sm">
          <span class="mb-1.5 block text-xs font-medium text-muted-text">开始日期</span>
          <input
            v-model="dateFrom"
            data-testid="dataset-date-from"
            type="date"
            required
            class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
          >
        </label>
        <label class="text-sm">
          <span class="mb-1.5 block text-xs font-medium text-muted-text">结束日期</span>
          <input
            v-model="dateTo"
            data-testid="dataset-date-to"
            type="date"
            required
            class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
          >
        </label>
      </div>

      <div class="rounded-xl border border-cyan/20 bg-cyan/10 p-3 text-xs leading-5 text-secondary-text">
        <p class="font-medium text-foreground">数据范围说明</p>
        <p class="mt-1">
          将按所选市场的固定 Universe 获取日频行情、基准和特征数据。默认范围为最近五年，构建过程由 Celery 异步执行。
        </p>
      </div>

      <div class="flex flex-col-reverse gap-2 border-t border-border/60 pt-4 sm:flex-row sm:justify-end">
        <Button variant="ghost" :disabled="submitting" @click="requestClose">取消</Button>
        <Button
          type="submit"
          data-testid="submit-dataset-build"
          :disabled="!dateRangeValid"
          :is-loading="submitting"
          loading-text="提交中"
        >
          提交构建任务
        </Button>
      </div>
    </form>
  </Dialog>
</template>
