<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { IntradayConfirmation, Portfolio } from '@/types/quant';
import { actionLabels, formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { ref, watch } from 'vue';

const { market } = useQuantMarket();
const item = ref<Portfolio | null>(null);
const confirmations = ref<Record<string, IntradayConfirmation>>({});
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
let requestVersion = 0;
const confirmationLabels: Record<string, string> = {
  confirm: '确认入场',
  wait: '等待确认',
  reject: '拒绝入场',
  expired: '已过期',
  insufficient_data: '数据不足',
};

watch(market, async (current) => {
  const version = ++requestVersion;
  item.value = null;
  confirmations.value = {};
  error.value = null;
  loading.value = true;
  const results = await Promise.allSettled([
    quantApi.portfolio(current),
    quantApi.confirmations(current),
  ]);
  if (version !== requestVersion) return;
  if (results[0].status === 'fulfilled') item.value = results[0].value;
  else error.value = getParsedApiError(results[0].reason);
  if (results[1].status === 'fulfilled') {
    confirmations.value = Object.fromEntries(results[1].value.map((row) => [row.code, row]));
  }
  loading.value = false;
}, { immediate: true });
</script>

<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        组合建议
      </h2>
      <p class="text-xs text-muted-text">
        研究建议，不执行真实券商订单，也不保证收益。
      </p>
    </header>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="py-12 text-center text-muted-text"
    >
      加载中...
    </div>
    <template v-else-if="item">
      <section class="grid gap-3 sm:grid-cols-3">
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-text">
            交易日
          </p><p>{{ item.tradeDate }}</p>
        </div>
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-text">
            目标总仓位
          </p><p>{{ formatPercent(item.targetEquityExposure) }}</p>
        </div>
        <div class="rounded-xl border border-border bg-card p-3">
          <p class="text-xs text-muted-text">
            最大总仓位
          </p><p>{{ formatPercent(item.maxEquityExposure) }}</p>
        </div>
      </section>
      <div
        v-if="item.warnings.length"
        class="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning"
      >
        {{ item.warnings.join('；') }}
      </div>
      <div class="overflow-x-auto rounded-2xl border border-border bg-card">
        <table class="w-full text-sm">
          <thead class="text-left text-xs text-muted-text">
            <tr>
              <th class="p-3">
                股票
              </th><th>行业</th><th>动作</th><th>当前权重</th><th>目标权重</th><th>变化</th><th>得分</th><th>预测收益</th><th>分钟确认</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in item.items"
              :key="row.id"
              class="border-t border-border"
            >
              <td class="p-3">
                {{ row.code }}
              </td><td>{{ row.sectorKey ?? '—' }}</td><td>{{ actionLabels[row.action] ?? row.action }}</td><td>{{ formatPercent(row.currentWeight) }}</td><td>{{ formatPercent(row.targetWeight) }}</td><td>{{ formatPercent(row.weightChange) }}</td><td>{{ formatScore(row.finalScore) }}</td><td>{{ formatPredictedReturn(row.predictedReturn) }}</td>
              <td>
                <span>{{ confirmationLabels[confirmations[row.code]?.decision] ?? '等待确认' }}</span><details
                  v-if="confirmations[row.code]"
                  class="text-xs text-muted-text"
                >
                  <summary>确认详情</summary><p>价格 {{ formatScore(confirmations[row.code].price) }} / VWAP {{ formatScore(confirmations[row.code].vwap) }}</p><p>{{ confirmations[row.code].reasons.join('；') }}</p>
                </details>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <EmptyState
      v-else
      :title="market === 'CN' ? 'A股组合建议尚未就绪' : '暂无组合建议'"
      description="当前市场尚未生成可展示的组合建议。"
    />
  </div>
</template>
