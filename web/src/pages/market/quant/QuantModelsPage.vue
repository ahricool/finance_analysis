<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import QuantTrainingDialog from '@/components/quant/QuantTrainingDialog.vue';
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
  await router.push({ path: '/market/quant/datasets', query: { market: targetMarket, build: '1' } });
}

watch(market, (current) => {
  trainingOpen.value = false;
  createdRun.value = null;
  void load(current);
}, { immediate: true });

watch(
  () => [router.currentRoute.value.query.createdRun, router.currentRoute.value.query.taskId] as const,
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
        <h2 class="text-lg font-semibold">模型运行</h2>
        <p class="text-xs text-muted-text">
          候选模型必须由管理员手动发布，训练不会自动替换 production。
        </p>
      </div>
      <Button v-if="isAdmin" data-testid="open-quant-training" @click="openTraining">
        创建训练任务
      </Button>
    </header>

    <ApiErrorAlert v-if="error" :error="error" />
    <InlineAlert v-if="createdRun" variant="success" title="训练任务已创建">
      ModelRun #{{ createdRun.modelRunId }} 已提交，训练将在后台执行。
      <template #action>
        <div class="flex flex-wrap gap-2">
          <RouterLink
            :to="{ path: `/market/quant/models/${createdRun.modelRunId}`, query: { market: createdRun.market } }"
            class="inline-flex h-9 items-center rounded-xl border border-success/30 px-3 text-sm font-medium hover:bg-success/10"
          >
            查看模型运行
          </RouterLink>
          <RouterLink
            to="/tasks/runs"
            class="inline-flex h-9 items-center rounded-xl border border-success/30 px-3 text-sm font-medium hover:bg-success/10"
          >
            查看任务详情
          </RouterLink>
        </div>
      </template>
    </InlineAlert>
    <div v-if="loading" class="py-12 text-center text-muted-text">加载中...</div>
    <div v-else-if="rows.length" class="overflow-x-auto rounded-2xl border border-border bg-card">
      <table class="w-full text-sm">
        <thead class="text-left text-xs text-muted-text">
          <tr>
            <th class="p-3">模型</th>
            <th>版本</th>
            <th>状态</th>
            <th>训练/测试区间</th>
            <th>Rank IC</th>
            <th>Top10超额</th>
            <th>进度</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rows" :key="item.id" class="border-t border-border">
            <td class="p-3">
              <RouterLink
                :to="{ path: `/market/quant/models/${item.id}`, query: marketQuery() }"
                class="text-primary"
              >
                {{ item.modelKey }}
              </RouterLink>
            </td>
            <td>{{ item.modelVersion }}</td>
            <td>{{ item.status }}</td>
            <td>{{ item.trainStart ?? '—' }} → {{ item.testEnd ?? '—' }}</td>
            <td>{{ formatScore(item.metrics.rankIc) }}</td>
            <td>{{ formatScore(item.metrics.top10ExcessReturnPct) }}%</td>
            <td>{{ item.progress }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      :title="market === 'CN' ? 'A股模型尚未训练' : '暂无模型运行'"
      description="当前市场还没有模型运行记录。管理员可以选择已就绪数据集创建训练任务。"
    />

    <QuantTrainingDialog
      v-if="isAdmin"
      :is-open="trainingOpen"
      :market="market"
      @close="trainingOpen = false"
      @created="handleCreated"
      @open-dataset-builder="openDatasetBuilder"
    />
  </div>
</template>
