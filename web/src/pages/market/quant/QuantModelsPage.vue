<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import QuantTrainingDrawer from '@/components/quant/QuantTrainingDrawer.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { useAuthStore } from '@/stores/authStore';
import type { ModelRun } from '@/types/quant';
import { formatScore } from '@/utils/quant';

const router = useRouter();
const auth = useAuthStore();
const { market, marketQuery } = useQuantMarket();
const rows = ref<ModelRun[]>([]);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const trainingOpen = ref(false);
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

async function handleCreated(runId: number): Promise<void> {
  trainingOpen.value = false;
  await router.push({ path: `/market/quant/models/${runId}`, query: marketQuery() });
}

watch(market, (current) => {
  trainingOpen.value = false;
  void load(current);
}, { immediate: true });
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
      description="当前市场还没有模型运行记录。管理员可以在这里创建数据集并启动训练。"
    />

    <QuantTrainingDrawer
      v-if="isAdmin"
      :is-open="trainingOpen"
      :market="market"
      @close="trainingOpen = false"
      @created="handleCreated"
    />
  </div>
</template>
