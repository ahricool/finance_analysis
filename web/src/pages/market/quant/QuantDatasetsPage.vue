<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { quantApi } from '@/api/quant';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import QuantDatasetBuildDialog from '@/components/quant/QuantDatasetBuildDialog.vue';
import QuantTrainingDialog from '@/components/quant/QuantTrainingDialog.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { useAuthStore } from '@/stores/authStore';
import type {
  DatasetBuildAccepted,
  ModelRunCreateAccepted,
  QuantDatasetSnapshot,
  QuantMarket,
} from '@/types/quant';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { computed, ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { market, setMarket } = useQuantMarket();
const rows = ref<QuantDatasetSnapshot[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const buildOpen = ref(false);
const trainingOpen = ref(false);
const trainingDatasetId = ref<number | null>(null);
const submittedBuild = ref<DatasetBuildAccepted | null>(null);
const isAdmin = computed(() => auth.currentUser?.role === 'admin');
let requestVersion = 0;

const universeByMarket: Record<QuantMarket, { name: string; key: string }> = {
  US: { name: 'S&P 500', key: 'us_sp500' },
  CN: { name: '沪深300', key: 'cn_csi300' },
};

function statusLabel(status: QuantDatasetSnapshot['status']): string {
  return { pending: '等待中', building: '构建中', ready: '已就绪', failed: '失败' }[status];
}

function statusVariant(status: QuantDatasetSnapshot['status']): 'default' | 'info' | 'success' | 'danger' {
  if (status === 'building') return 'info';
  if (status === 'ready') return 'success';
  if (status === 'failed') return 'danger';
  return 'default';
}

function priceModeLabel(value: string): string {
  if (value === 'forward_adjusted') return '前复权';
  if (value === 'raw') return '不复权';
  return value;
}

function formatCount(value: number): string {
  return value.toLocaleString('zh-CN');
}

function validationText(item: QuantDatasetSnapshot): string {
  const result = item.validationResult ?? {};
  const preferred = result.reason ?? result.error ?? result.message;
  if (typeof preferred === 'string' && preferred.trim()) return preferred;
  if (Object.keys(result).length) return JSON.stringify(result);
  return item.status === 'failed' ? '未提供失败原因' : '—';
}

function canTrain(item: QuantDatasetSnapshot): boolean {
  return item.status === 'ready' && Boolean(item.artifactUri);
}

async function load(current = market.value): Promise<void> {
  const version = ++requestVersion;
  loading.value = true;
  error.value = null;
  try {
    const value = await quantApi.datasets(current);
    if (version === requestVersion) rows.value = value;
  } catch (err) {
    if (version === requestVersion) error.value = getParsedApiError(err);
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}

function openTraining(item: QuantDatasetSnapshot): void {
  if (!canTrain(item)) return;
  trainingDatasetId.value = item.id;
  trainingOpen.value = true;
}

async function handleBuildSubmitted(result: DatasetBuildAccepted): Promise<void> {
  buildOpen.value = false;
  submittedBuild.value = result;
  if (result.market !== market.value) {
    await setMarket(result.market);
  } else {
    await load();
  }
}

async function handleTrainingCreated(result: ModelRunCreateAccepted): Promise<void> {
  trainingOpen.value = false;
  await router.push({
    path: '/market/quant/models',
    query: { market: result.market, createdRun: String(result.modelRunId), taskId: result.taskId },
  });
}

async function openDatasetBuilder(targetMarket: QuantMarket): Promise<void> {
  trainingOpen.value = false;
  if (targetMarket !== market.value) await setMarket(targetMarket);
  buildOpen.value = true;
}

watch(market, (current) => {
  buildOpen.value = false;
  trainingOpen.value = false;
  void load(current);
}, { immediate: true });

watch(
  () => [route.query.build, isAdmin.value] as const,
  ([build, admin]) => {
    if (build === '1' && admin) buildOpen.value = true;
  },
  { immediate: true },
);
</script>

<template>
  <div class="min-w-0 space-y-4">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">数据集</h2>
        <p class="text-xs text-muted-text">
          数据集由后台异步构建；只有已就绪且存在制品的数据集可以用于训练。
        </p>
      </div>
      <Button v-if="isAdmin" data-testid="open-dataset-build" @click="buildOpen = true">
        构建数据集
      </Button>
    </header>

    <ApiErrorAlert v-if="error" :error="error" @dismiss="error = null" />
    <InlineAlert v-if="submittedBuild" variant="success" title="数据集构建任务已提交">
      任务 ID：<span class="break-all font-mono">{{ submittedBuild.taskId }}</span>。完成后刷新列表查看状态。
      <template #action>
        <RouterLink
          to="/tasks/runs"
          class="inline-flex h-9 items-center rounded-xl border border-success/30 px-3 text-sm font-medium hover:bg-success/10"
        >
          前往任务中心
        </RouterLink>
      </template>
    </InlineAlert>

    <div v-if="loading" class="py-12 text-center text-muted-text">加载中...</div>
    <div v-else-if="rows.length" class="max-w-full overflow-x-auto rounded-2xl border border-border bg-card">
      <table class="min-w-[1680px] w-full text-left text-sm" data-testid="quant-dataset-table">
        <thead class="border-b border-border text-xs text-muted-text">
          <tr>
            <th class="px-3 py-3 font-medium">数据集 ID</th>
            <th class="px-3 py-3 font-medium">市场</th>
            <th class="px-3 py-3 font-medium">Universe</th>
            <th class="px-3 py-3 font-medium">开始日期</th>
            <th class="px-3 py-3 font-medium">结束日期</th>
            <th class="px-3 py-3 font-medium">状态</th>
            <th class="px-3 py-3 font-medium">股票数量</th>
            <th class="px-3 py-3 font-medium">数据行数</th>
            <th class="px-3 py-3 font-medium">价格模式</th>
            <th class="px-3 py-3 font-medium">特征版本</th>
            <th class="px-3 py-3 font-medium">创建时间</th>
            <th class="px-3 py-3 font-medium">完成时间</th>
            <th class="min-w-[240px] px-3 py-3 font-medium">验证结果 / 失败原因</th>
            <th class="px-3 py-3 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rows" :key="item.id" class="border-b border-border/60 last:border-0">
            <td class="whitespace-nowrap px-3 py-4 font-mono">#{{ item.id }}</td>
            <td class="whitespace-nowrap px-3 py-4">{{ item.market }}</td>
            <td class="whitespace-nowrap px-3 py-4">
              <p class="font-medium text-foreground">{{ universeByMarket[item.market].name }}</p>
              <p class="font-mono text-xs text-muted-text">{{ universeByMarket[item.market].key }}</p>
            </td>
            <td class="whitespace-nowrap px-3 py-4">{{ item.dateFrom }}</td>
            <td class="whitespace-nowrap px-3 py-4">{{ item.dateTo }}</td>
            <td class="whitespace-nowrap px-3 py-4">
              <Badge :variant="statusVariant(item.status)">{{ statusLabel(item.status) }}</Badge>
            </td>
            <td class="whitespace-nowrap px-3 py-4 tabular-nums">{{ formatCount(item.symbolCount) }}</td>
            <td class="whitespace-nowrap px-3 py-4 tabular-nums">{{ formatCount(item.rowCount) }}</td>
            <td class="whitespace-nowrap px-3 py-4">{{ priceModeLabel(item.priceMode) }}</td>
            <td class="whitespace-nowrap px-3 py-4 font-mono text-xs">{{ item.featureVersion }}</td>
            <td class="whitespace-nowrap px-3 py-4 text-xs">{{ formatDateTimeInDisplayTimezone(item.createdAt) }}</td>
            <td class="whitespace-nowrap px-3 py-4 text-xs">{{ formatDateTimeInDisplayTimezone(item.finishedAt) }}</td>
            <td class="max-w-[320px] px-3 py-4 text-xs text-secondary-text">
              <span class="line-clamp-3 break-all">{{ validationText(item) }}</span>
            </td>
            <td class="whitespace-nowrap px-3 py-4">
              <Button
                v-if="canTrain(item) && isAdmin"
                variant="secondary"
                size="sm"
                :data-testid="`train-with-dataset-${item.id}`"
                @click="openTraining(item)"
              >
                使用此数据集训练
              </Button>
              <span v-else-if="item.status === 'ready' && !item.artifactUri" class="text-xs text-warning">缺少数据制品</span>
              <span v-else class="text-xs text-muted-text">不可训练</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      title="暂无数据集"
      description="构建任务提交后会在后台运行，生成记录后即可在这里查看状态。"
    >
      <template v-if="isAdmin" #action>
        <Button variant="secondary" @click="buildOpen = true">构建数据集</Button>
      </template>
    </EmptyState>

    <QuantDatasetBuildDialog
      v-if="isAdmin"
      :is-open="buildOpen"
      :market="market"
      @close="buildOpen = false"
      @submitted="handleBuildSubmitted"
    />
    <QuantTrainingDialog
      v-if="isAdmin"
      :is-open="trainingOpen"
      :market="market"
      :initial-dataset-id="trainingDatasetId"
      @close="trainingOpen = false"
      @created="handleTrainingCreated"
      @open-dataset-builder="openDatasetBuilder"
    />
  </div>
</template>
