<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { ModelRun } from '@/types/quant';
import { formatScore } from '@/utils/quant';
import { ref, watch } from 'vue';
const { market, marketQuery } = useQuantMarket();
const rows = ref<ModelRun[]>([]); const error = ref<ParsedApiError | null>(null); const loading = ref(false); let requestVersion = 0;
watch(market, async (current) => { const version = ++requestVersion; rows.value = []; error.value = null; loading.value = true; try { const value = await quantApi.models(current); if (version === requestVersion) rows.value = value; } catch (err) { if (version === requestVersion) error.value = getParsedApiError(err); } finally { if (version === requestVersion) loading.value = false; } }, { immediate: true });
</script>
<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        模型运行
      </h2><p class="text-xs text-muted-text">
        候选模型必须由管理员手动发布，训练不会自动替换 production。
      </p>
    </header><ApiErrorAlert
      v-if="error"
      :error="error"
    /><div
      v-if="loading"
      class="py-12 text-center text-muted-text"
    >
      加载中...
    </div><div
      v-else-if="rows.length"
      class="overflow-x-auto rounded-2xl border border-border bg-card"
    >
      <table class="w-full text-sm">
        <thead class="text-left text-xs text-muted-text">
          <tr>
            <th class="p-3">
              模型
            </th><th>版本</th><th>状态</th><th>训练/测试区间</th><th>Rank IC</th><th>Top10超额</th><th>进度</th>
          </tr>
        </thead><tbody>
          <tr
            v-for="item in rows"
            :key="item.id"
            class="border-t border-border"
          >
            <td class="p-3">
              <RouterLink
                :to="{path:`/market/quant/models/${item.id}`,query:marketQuery()}"
                class="text-primary"
              >
                {{ item.modelKey }}
              </RouterLink>
            </td><td>{{ item.modelVersion }}</td><td>{{ item.status }}</td><td>{{ item.trainStart ?? '—' }} → {{ item.testEnd ?? '—' }}</td><td>{{ formatScore(item.metrics.rankIc) }}</td><td>{{ formatScore(item.metrics.top10ExcessReturnPct) }}%</td><td>{{ item.progress }}%</td>
          </tr>
        </tbody>
      </table>
    </div><EmptyState
      v-else
      :title="market==='CN'?'A股模型尚未训练':'暂无模型运行'"
      description="当前市场还没有模型运行记录。"
    />
  </div>
</template>
