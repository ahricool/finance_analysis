<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { quantApi } from '@/api/quant';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import QuantDatasetBuildDialog from '@/components/quant/QuantDatasetBuildDialog.vue';
import QuantTrainingDialog from '@/components/quant/QuantTrainingDialog.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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
const deleteTarget = ref<QuantDatasetSnapshot | null>(null);
const deletingId = ref<number | null>(null);
const deleteSuccess = ref<string | null>(null);
const isAdmin = computed(() => auth.currentUser?.role === 'admin');
let requestVersion = 0;

const universeByMarket: Record<QuantMarket, { name: string; key: string }> = {
  US: { name: 'S&P 500', key: 'us_sp500' },
  CN: { name: '沪深300', key: 'cn_csi300' },
};

function statusLabel(status: QuantDatasetSnapshot['status']): string {
  return { pending: '等待中', building: '构建中', ready: '已就绪', failed: '失败' }[status];
}

function statusVariant(
  status: QuantDatasetSnapshot['status'],
): 'default' | 'info' | 'success' | 'destructive' {
  if (status === 'building') return 'info';
  if (status === 'ready') return 'success';
  if (status === 'failed') return 'destructive';
  return 'default';
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
  return item.trainable;
}

function canDelete(item: QuantDatasetSnapshot): boolean {
  return item.status !== 'pending' && item.status !== 'building';
}

function requestDelete(item: QuantDatasetSnapshot): void {
  if (!canDelete(item)) return;
  deleteTarget.value = item;
}

async function confirmDelete(): Promise<void> {
  const item = deleteTarget.value;
  if (!item || deletingId.value !== null) return;
  deleteTarget.value = null;
  deletingId.value = item.id;
  error.value = null;
  deleteSuccess.value = null;
  try {
    await quantApi.deleteDataset(item.id, item.market);
    rows.value = rows.value.filter((row) => row.id !== item.id);
    deleteSuccess.value = `数据集 #${item.id} 及其制品已删除。`;
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    deletingId.value = null;
  }
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

watch(
  market,
  (current) => {
    buildOpen.value = false;
    trainingOpen.value = false;
    void load(current);
  },
  { immediate: true },
);

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
        <h2 class="text-lg font-semibold">
          数据集
        </h2>
        <p class="text-xs text-muted-foreground">
          数据集由后台异步构建；只有已就绪且存在制品的数据集可以用于训练。
        </p>
      </div>
      <Button
        v-if="isAdmin"
        data-testid="open-dataset-build"
        @click="buildOpen = true"
      >
        构建数据集
      </Button>
    </header>

    <ApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />
    <Alert
      v-if="deleteSuccess"
      variant="success"
    >
      <AlertTitle>删除成功</AlertTitle>
      <AlertDescription class="text-current/80">
        {{ deleteSuccess }}
      </AlertDescription>
    </Alert>
    <Alert
      v-if="submittedBuild"
      variant="success"
    >
      <AlertTitle>数据集构建任务已提交</AlertTitle>
      <AlertDescription class="text-current/80">
        任务 ID：<span class="break-all font-mono">{{ submittedBuild.taskId }}</span>。完成后刷新列表查看状态。
      </AlertDescription>
      <Button
        as-child
        variant="outline"
        size="sm"
        class="mt-3"
      >
        <RouterLink to="/tasks/runs">
          前往任务中心
        </RouterLink>
      </Button>
    </Alert>

    <div
      v-if="loading"
      class="space-y-3"
    >
      <Skeleton
        v-for="index in 5"
        :key="index"
        class="h-16 w-full"
      />
    </div>
    <template v-else-if="rows.length">
      <div
        class="space-y-3 md:hidden"
        data-testid="quant-dataset-mobile-list"
      >
        <Card
          v-for="item in rows"
          :key="item.id"
        >
          <CardHeader>
            <CardTitle class="font-mono text-base">
              #{{ item.id }} · {{ item.market }}
            </CardTitle><CardDescription>{{ universeByMarket[item.market].name }} · {{ item.featureVersion }}</CardDescription><Badge :variant="statusVariant(item.status)">
              {{ statusLabel(item.status) }}
            </Badge>
          </CardHeader>
          <CardContent>
            <dl class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <dt class="text-muted-foreground">
                  日期范围
                </dt>
                <dd class="mt-1 font-medium">
                  {{ item.dateFrom }}<br />{{ item.dateTo }}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  Universe 覆盖
                </dt>
                <dd class="mt-1 font-medium">
                  {{ formatCount(item.symbolCount) }} / {{ formatCount(item.universeMemberCount)
                  }}<br />{{ (item.universeCoverageRatio * 100).toFixed(1) }}%
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  数据行数
                </dt>
                <dd class="mt-1 font-medium tabular-nums">
                  {{ formatCount(item.rowCount) }}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  日线价格
                </dt>
                <dd class="mt-1 font-medium">
                  前复权
                </dd>
              </div>
            </dl><p class="mt-3 line-clamp-2 break-all text-xs text-muted-foreground">
              {{ validationText(item) }}
            </p>
          </CardContent>
          <CardFooter class="gap-2">
            <Button
              v-if="canTrain(item) && isAdmin"
              variant="secondary"
              size="sm"
              class="flex-1"
              @click="openTraining(item)"
            >
              使用此数据集训练
            </Button>
            <p
              v-else
              class="flex-1 text-center text-xs text-muted-foreground"
            >
              当前数据集不可训练
            </p>
            <Button
              v-if="isAdmin"
              variant="destructive"
              size="sm"
              :disabled="!canDelete(item) || deletingId === item.id"
              :title="canDelete(item) ? '删除数据集' : '等待中或构建中的数据集不能删除'"
              :data-testid="`delete-dataset-${item.id}`"
              @click="requestDelete(item)"
            >
              {{ deletingId === item.id ? '删除中…' : '删除' }}
            </Button>
          </CardFooter>
        </Card>
      </div>
      <Card class="hidden md:block">
        <CardHeader><CardTitle>数据集快照</CardTitle><CardDescription>构建状态、覆盖率、数据口径与训练可用性。</CardDescription></CardHeader><CardContent>
          <Table
            class="min-w-[1680px] w-full text-left text-sm"
            data-testid="quant-dataset-table"
          >
            <TableHeader class="border-b border-border text-xs text-muted-foreground">
              <TableRow>
                <TableHead class="px-3 py-3 font-medium">
                  数据集 ID
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  市场
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  Universe
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  开始日期
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  结束日期
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  状态
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  股票数量
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  数据行数
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  价格模式
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  特征版本
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  创建时间
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  完成时间
                </TableHead>
                <TableHead class="min-w-[240px] px-3 py-3 font-medium">
                  验证结果 / 失败原因
                </TableHead>
                <TableHead class="px-3 py-3 font-medium">
                  操作
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="item in rows"
                :key="item.id"
                class="border-b border-border/60 last:border-0"
              >
                <TableCell class="whitespace-nowrap px-3 py-4 font-mono">
                  #{{ item.id }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  {{ item.market }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  <p class="font-medium text-foreground">
                    {{ universeByMarket[item.market].name }}
                  </p>
                  <p class="font-mono text-xs text-muted-foreground">
                    {{ universeByMarket[item.market].key }}
                  </p>
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  {{ item.dateFrom }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  {{ item.dateTo }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  <Badge :variant="statusVariant(item.status)">
                    {{ statusLabel(item.status) }}
                  </Badge>
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4 tabular-nums">
                  {{ formatCount(item.symbolCount) }} / {{ formatCount(item.universeMemberCount) }}
                  <p class="text-xs text-muted-foreground">
                    {{ (item.universeCoverageRatio * 100).toFixed(1) }}%
                  </p>
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4 tabular-nums">
                  {{ formatCount(item.rowCount) }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  前复权
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4 font-mono text-xs">
                  {{ item.featureVersion }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4 text-xs">
                  {{ formatDateTimeInDisplayTimezone(item.createdAt) }}
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4 text-xs">
                  {{ formatDateTimeInDisplayTimezone(item.finishedAt) }}
                </TableCell>
                <TableCell class="max-w-[320px] px-3 py-4 text-xs text-muted-foreground">
                  <span class="line-clamp-3 break-all">{{ validationText(item) }}</span>
                </TableCell>
                <TableCell class="whitespace-nowrap px-3 py-4">
                  <div class="flex items-center gap-2">
                    <Button
                      v-if="canTrain(item) && isAdmin"
                      variant="secondary"
                      size="sm"
                      :data-testid="`train-with-dataset-${item.id}`"
                      @click="openTraining(item)"
                    >
                      使用此数据集训练
                    </Button>
                    <span
                      v-else-if="item.status === 'ready' && !item.artifactUri"
                      class="text-xs text-warning"
                    >缺少数据制品</span>
                    <span
                      v-else-if="
                        item.status === 'ready' &&
                          item.universeCoverageRatio < item.minimumUniverseCoverage
                      "
                      class="text-xs text-warning"
                    >
                      Universe 覆盖率低于 {{ (item.minimumUniverseCoverage * 100).toFixed(0) }}%
                    </span>
                    <span
                      v-else
                      class="text-xs text-muted-foreground"
                    >不可训练</span>
                    <Button
                      v-if="isAdmin"
                      variant="destructive"
                      size="sm"
                      :disabled="!canDelete(item) || deletingId === item.id"
                      :title="canDelete(item) ? '删除数据集' : '等待中或构建中的数据集不能删除'"
                      :data-testid="`delete-dataset-desktop-${item.id}`"
                      @click="requestDelete(item)"
                    >
                      {{ deletingId === item.id ? '删除中…' : '删除' }}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </template>
    <Empty v-else>
      <EmptyHeader><EmptyTitle>暂无数据集</EmptyTitle><EmptyDescription>构建任务提交后会在后台运行，生成记录后即可在这里查看状态。</EmptyDescription></EmptyHeader>
      <div v-if="isAdmin">
        <Button
          variant="secondary"
          @click="buildOpen = true"
        >
          构建数据集
        </Button>
      </div>
    </Empty>

    <QuantDatasetBuildDialog
      v-if="isAdmin"
      :open="buildOpen"
      :market="market"
      @update:open="buildOpen = false"
      @submitted="handleBuildSubmitted"
    />
    <QuantTrainingDialog
      v-if="isAdmin"
      :open="trainingOpen"
      :market="market"
      :initial-dataset-id="trainingDatasetId"
      @update:open="trainingOpen = false"
      @created="handleTrainingCreated"
      @open-dataset-builder="openDatasetBuilder"
    />
    <AppConfirmDialog
      :open="deleteTarget !== null"
      title="删除数据集"
      :description="`确认删除数据集 #${deleteTarget?.id ?? ''}？数据库记录和 /data 下对应制品会一并删除；若模型运行仍在引用它，删除会被拒绝。`"
      confirm-text="确认删除"
      destructive
      @update:open="deleteTarget = $event ? deleteTarget : null"
      @confirm="confirmDelete"
    />
  </div>
</template>
