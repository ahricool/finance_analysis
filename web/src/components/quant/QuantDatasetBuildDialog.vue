<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { quantApi } from '@/api/quant';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import type { DatasetBuildAccepted, QuantMarket } from '@/types/quant';
import { computed, ref, watch } from 'vue';

const props = defineProps<{
  open: boolean;
  market: QuantMarket;
}>();

const emit = defineEmits<{
  'update:open': [value: boolean];
  submitted: [result: DatasetBuildAccepted];
}>();

const selectedMarket = ref<QuantMarket>('US');
const dateFrom = ref('');
const dateTo = ref('');
const submitting = ref(false);
const error = ref<ParsedApiError | null>(null);

const universe = computed(() =>
  selectedMarket.value === 'US'
    ? { name: 'S&P 500', key: 'us_sp500' }
    : { name: '沪深300', key: 'cn_csi300' },
);
const dateRangeValid = computed(() =>
  Boolean(dateFrom.value && dateTo.value && dateFrom.value <= dateTo.value),
);

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function resetForm(): void {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 3);
  selectedMarket.value = props.market;
  dateFrom.value = formatDateInput(start);
  dateTo.value = formatDateInput(end);
  error.value = null;
}

function requestClose(): void {
  if (!submitting.value) emit('update:open', false);
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

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) resetForm();
  },
);
</script>

<template>
  <Dialog
    :open="open"
    @update:open="requestClose"
  >
    <DialogContent class="max-w-2xl">
      <DialogHeader>
        <DialogTitle>构建数据集</DialogTitle>
        <DialogDescription>
          提交后将在后台构建数据集。任务完成且状态变为 ready 后，才能用于模型训练。
        </DialogDescription>
      </DialogHeader>
      <form
        class="space-y-5"
        data-testid="dataset-build-form"
        @submit.prevent="submit"
      >
        <ApiErrorAlert
          v-if="error"
          :error="error"
          @dismiss="error = null"
        />

        <fieldset>
          <legend class="mb-2 text-xs font-medium text-muted-foreground">
            市场
          </legend>
          <div
            class="grid grid-cols-2 gap-2"
            role="radiogroup"
            aria-label="数据集市场"
          >
            <label
              v-for="option in [
                { value: 'US', label: '美股 · US' },
                { value: 'CN', label: 'A股 · CN' },
              ]"
              :key="option.value"
              class="cursor-pointer rounded-xl border p-3 text-sm transition-colors"
              :class="
                selectedMarket === option.value
                  ? 'border-primary/50 bg-primary/10 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:bg-muted'
              "
            >
              <input
                v-model="selectedMarket"
                class="sr-only"
                type="radio"
                :value="option.value"
              />
              <span class="font-medium">{{ option.label }}</span>
            </label>
          </div>
        </fieldset>

        <label class="block text-sm">
          <span class="mb-1.5 block text-xs font-medium text-muted-foreground">Universe（固定）</span>
          <input
            :value="`${universe.name} / ${universe.key}`"
            readonly
            data-testid="dataset-universe"
            class="h-10 w-full rounded-xl border border-border bg-card px-3 text-sm text-muted-foreground"
          />
        </label>

        <div class="grid gap-4 sm:grid-cols-2">
          <AppDatePicker
            v-model="dateFrom"
            label="开始日期"
            data-testid="dataset-date-from"
          />
          <AppDatePicker
            v-model="dateTo"
            label="结束日期"
            data-testid="dataset-date-to"
          />
        </div>

        <div
          class="rounded-lg border bg-muted/50 p-3 text-xs leading-5 text-muted-foreground"
        >
          <p class="font-medium text-foreground">
            数据范围说明
          </p>
          <p class="mt-1">
            将按所选市场的固定 Universe 获取日频行情、基准和特征数据。默认范围为最近三年，构建过程由
            Celery 异步执行。
          </p>
        </div>

        <Separator />
        <DialogFooter>
          <Button
            variant="ghost"
            :disabled="submitting"
            @click="requestClose"
          >
            取消
          </Button>
          <LoadingButton
            type="submit"
            data-testid="submit-dataset-build"
            :disabled="!dateRangeValid"
            :loading="submitting"
            loading-text="提交中"
          >
            提交构建任务
          </LoadingButton>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>
