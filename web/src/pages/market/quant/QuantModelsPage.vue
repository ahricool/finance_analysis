<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import QuantTrainingDialog from '@/components/quant/QuantTrainingDialog.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { useAuthStore } from '@/stores/authStore';
import type { ModelRun, ModelRunCreateAccepted, QuantMarket } from '@/types/quant';
import { formatScore } from '@/utils/quant';

const router = useRouter();
const auth = useAuthStore();
const { market, marketQuery } = useQuantMarket();
const rows = ref<ModelRun[]>([]);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const trainingOpen = ref(false);
const createdRun = ref<ModelRunCreateAccepted | null>(null);
const isAdmin = computed(() => auth.currentUser?.role === 'admin');
let requestVersion = 0;

async function load(current = market.value): Promise<void> {
  const version = ++requestVersion;
  rows.value = [];
  error.value = null;
  loading.value = true;
  try {
    const value = await quantApi.models(current);
    if (version === requestVersion) rows.value = value;
  } catch (err) {
    if (version === requestVersion) error.value = getParsedApiError(err);
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}

function openTraining(): void {
  trainingOpen.value = true;
}

async function handleCreated(result: ModelRunCreateAccepted): Promise<void> {
  trainingOpen.value = false;
  if (result.market !== market.value) {
    await router.push({ path: '/market/quant/models', query: { market: result.market } });
  } else {
    await load();
  }
  createdRun.value = result;
}

async function openDatasetBuilder(targetMarket: QuantMarket): Promise<void> {
  trainingOpen.value = false;
  await router.push({
    path: '/market/quant/datasets',
    query: { market: targetMarket, build: '1' },
  });
}

watch(
  market,
  (current) => {
    trainingOpen.value = false;
    createdRun.value = null;
    void load(current);
  },
  { immediate: true },
);

watch(
  () =>
    [router.currentRoute.value.query.createdRun, router.currentRoute.value.query.taskId] as const,
  ([runId, taskId]) => {
    const id = Number(runId);
    if (!Number.isInteger(id) || id <= 0 || typeof taskId !== 'string') return;
    createdRun.value = { modelRunId: id, taskId, status: 'pending', market: market.value };
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">
          模型运行
        </h2>
        <p class="text-xs text-muted-foreground">
          候选模型必须由管理员手动发布，训练不会自动替换 production。
        </p>
      </div>
      <Button
        v-if="isAdmin"
        data-testid="open-quant-training"
        @click="openTraining"
      >
        创建训练任务
      </Button>
    </header>

    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <Alert
      v-if="createdRun"
      variant="success"
    >
      <AlertTitle>训练任务已创建</AlertTitle>
      <AlertDescription class="text-current/80">
        ModelRun #{{ createdRun.modelRunId }} 已提交，训练将在后台执行。
      </AlertDescription>
      <div class="mt-3 flex flex-wrap gap-2">
        <Button
          as-child
          variant="outline"
          size="sm"
        >
          <RouterLink
            :to="{
              path: `/market/quant/models/${createdRun.modelRunId}`,
              query: { market: createdRun.market },
            }"
          >
            查看模型运行
          </RouterLink>
        </Button>
        <Button
          as-child
          variant="outline"
          size="sm"
        >
          <RouterLink
            to="/tasks/runs"
          >
            查看任务详情
          </RouterLink>
        </Button>
      </div>
    </Alert>
    <div
      v-if="loading"
      class="space-y-3"
    >
      <Skeleton
        v-for="index in 5"
        :key="index"
        class="h-14 w-full"
      />
    </div>
    <Card v-else-if="rows.length">
      <CardHeader><CardTitle>模型运行列表</CardTitle><CardDescription>查看训练区间、核心指标和发布状态。</CardDescription></CardHeader>
      <CardContent class="hidden md:block">
        <Table>
          <TableHeader><TableRow><TableHead>模型</TableHead><TableHead>版本</TableHead><TableHead>状态</TableHead><TableHead>训练/测试区间</TableHead><TableHead>Rank IC</TableHead><TableHead>Top10超额</TableHead><TableHead>进度</TableHead></TableRow></TableHeader><TableBody>
            <TableRow
              v-for="item in rows"
              :key="item.id"
            >
              <TableCell>
                <RouterLink
                  :to="{ path: `/market/quant/models/${item.id}`, query: marketQuery() }"
                  class="font-medium underline-offset-4 hover:underline"
                >
                  {{ item.modelKey }}
                </RouterLink>
              </TableCell><TableCell>{{ item.modelVersion }}</TableCell><TableCell>
                <Badge variant="outline">
                  {{ item.status }}
                </Badge>
              </TableCell><TableCell>{{ item.trainStart ?? '—' }} → {{ item.testEnd ?? '—' }}</TableCell><TableCell>{{ formatScore(item.metrics.rankIc) }}</TableCell><TableCell>{{ formatScore(item.metrics.top10ExcessReturnPct) }}%</TableCell><TableCell>{{ item.progress }}%</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
      <CardContent class="space-y-3 md:hidden">
        <Card
          v-for="item in rows"
          :key="item.id"
        >
          <CardHeader>
            <CardTitle class="text-base">
              <RouterLink
                :to="{ path: `/market/quant/models/${item.id}`, query: marketQuery() }"
                class="font-medium underline-offset-4 hover:underline"
              >
                {{ item.modelKey }}
              </RouterLink>
            </CardTitle><CardDescription>{{ item.modelVersion }}</CardDescription><Badge variant="outline">
              {{ item.status }}
            </Badge>
          </CardHeader><CardContent class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p class="text-xs text-muted-foreground">
                Rank IC
              </p>{{ formatScore(item.metrics.rankIc) }}
            </div><div>
              <p class="text-xs text-muted-foreground">
                进度
              </p>{{ item.progress }}%
            </div>
          </CardContent>
        </Card>
      </CardContent>
    </Card>
    <Empty v-else>
      <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股模型尚未训练' : '暂无模型运行' }}</EmptyTitle><EmptyDescription>当前市场还没有模型运行记录。管理员可以选择已就绪数据集创建训练任务。</EmptyDescription></EmptyHeader>
    </Empty>

    <QuantTrainingDialog
      v-if="isAdmin"
      :open="trainingOpen"
      :market="market"
      @update:open="trainingOpen = false"
      @created="handleCreated"
      @open-dataset-builder="openDatasetBuilder"
    />
  </div>
</template>
