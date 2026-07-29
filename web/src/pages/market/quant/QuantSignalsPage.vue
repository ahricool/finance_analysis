<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import EmptyState from '@/components/app/AppEmptyState.vue';
import AppInput from '@/components/app/AppInput.vue';
import AppSelect from '@/components/app/AppSelect.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { SignalRanking } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { computed, ref, watch } from 'vue';

const { market, marketQuery } = useQuantMarket();
const ranking = ref<SignalRanking | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const filter = ref('');
const vetoed = ref('all');
const items = computed(
  () =>
    ranking.value?.items.filter(
      (item) =>
        (!filter.value || item.code.includes(filter.value.toUpperCase())) &&
        (vetoed.value === 'all' || String(item.vetoed) === vetoed.value),
    ) ?? [],
);
let requestVersion = 0;

watch(
  market,
  async (current) => {
    const version = ++requestVersion;
    ranking.value = null;
    error.value = null;
    loading.value = true;
    try {
      const value = await quantApi.signals(current);
      if (version === requestVersion) ranking.value = value;
    } catch (err) {
      if (version === requestVersion) error.value = getParsedApiError(err);
    } finally {
      if (version === requestVersion) loading.value = false;
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        模型选股排名
      </h2>
      <p class="text-xs text-muted-foreground">
        模型预测仅用于研究和组合建议，不代表真实订单。
        <span v-if="ranking?.modelVersion">当前版本：{{ ranking.modelVersion }}。</span>
      </p>
    </header>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="py-12 text-center text-muted-foreground"
    >
      加载中...
    </div>
    <template v-else>
      <div class="grid gap-2 sm:grid-cols-2">
        <AppInput
          v-model="filter"
          placeholder="股票代码"
        />
        <AppSelect
          v-model="vetoed"
          :options="[
            { value: 'all', label: '全部' },
            { value: 'true', label: '已否决' },
            { value: 'false', label: '未否决' },
          ]"
        />
      </div>
      <div
        v-if="items.length"
        class="overflow-x-auto rounded-2xl border border-border bg-card"
      >
        <table class="w-full text-sm">
          <thead class="text-left text-xs text-muted-foreground">
            <tr>
              <th class="p-3">
                排名
              </th>
              <th>股票</th>
              <th>最终/原始</th>
              <th>横截面</th>
              <th>时间序列</th>
              <th>预测收益</th>
              <th>目标仓位</th>
              <th>信号</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.id"
              class="border-t border-border"
            >
              <td class="p-3">
                {{ item.universeRank ?? '—' }}
              </td>
              <td>
                <RouterLink
                  :to="{ path: `/market/quant/signals/${item.code}`, query: marketQuery() }"
                  class="text-primary"
                >
                  {{ item.code }}
                </RouterLink>
              </td>
              <td>{{ formatScore(item.finalScore) }} / {{ formatScore(item.rawFinalScore) }}</td>
              <td>{{ formatScore(item.crossSectionScore) }}</td>
              <td>{{ formatScore(item.timeSeriesScore) }}</td>
              <td>{{ formatPredictedReturn(item.predictedReturn) }}</td>
              <td>{{ formatPercent(item.targetPosition) }}</td>
              <td>{{ item.vetoed ? 'blocked' : item.signal }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else
        :title="market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名'"
        description="当前市场没有可展示的生产模型信号。"
      />
    </template>
  </div>
</template>
