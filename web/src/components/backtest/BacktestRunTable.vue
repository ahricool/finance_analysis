<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import type { BacktestRun } from '@/types/backtests';
import { engineLabels, formatPct, marketLabels, statusLabels } from '@/utils/backtests';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { RouterLink } from 'vue-router';

defineProps<{ runs: BacktestRun[]; loading?: boolean }>();
const emit = defineEmits<{ reuse: [run: BacktestRun] }>();

function statusVariant(status: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'processing') return 'info';
  if (status === 'pending') return 'warning';
  return 'default';
}
</script>

<template>
  <section class="overflow-hidden rounded-2xl border border-border/70 bg-card/94 shadow-soft-card">
    <div class="border-b border-border/70 px-4 py-3">
      <h3 class="text-sm font-semibold text-foreground">
        历史回测
      </h3>
    </div>
    <div
      v-if="loading"
      class="p-8 text-center text-sm text-muted-text"
    >
      加载中...
    </div>
    <div
      v-else-if="!runs.length"
      class="p-8 text-center text-sm text-muted-text"
    >
      暂无回测记录
    </div>
    <div
      v-else
      class="overflow-x-auto"
    >
      <table class="min-w-[1050px] w-full text-left text-xs">
        <thead class="bg-elevated/60 text-muted-text">
          <tr>
            <th class="px-3 py-3">
              创建时间
            </th><th class="px-3 py-3">
              引擎
            </th><th class="px-3 py-3">
              策略
            </th>
            <th class="px-3 py-3">
              市场 / 标的
            </th><th class="px-3 py-3">
              日期范围
            </th><th class="px-3 py-3">
              状态
            </th>
            <th class="px-3 py-3">
              总收益
            </th><th class="px-3 py-3">
              基准收益
            </th><th class="px-3 py-3">
              交易次数
            </th><th class="px-3 py-3">
              操作
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border/60">
          <tr
            v-for="run in runs"
            :key="run.id"
            class="text-secondary-text"
          >
            <td class="px-3 py-3">
              {{ formatDateTimeInDisplayTimezone(run.createdAt) }}
            </td>
            <td class="px-3 py-3">
              <Badge :variant="run.engine === 'backtrader' ? 'success' : 'info'">
                {{ engineLabels[run.engine] }}<span v-if="run.engine === 'backtrader'"> · 推荐</span>
              </Badge>
            </td>
            <td class="px-3 py-3">
              {{ run.strategyName }}
            </td>
            <td class="px-3 py-3">
              {{ marketLabels[run.market] }} · {{ run.code }}
            </td>
            <td class="px-3 py-3">
              {{ run.startDate }} — {{ run.endDate }}
            </td>
            <td class="px-3 py-3">
              <Badge :variant="statusVariant(run.status)">
                {{ statusLabels[run.status] }}
              </Badge>
              <span
                v-if="run.status === 'processing' || run.status === 'pending'"
                class="ml-2"
              >{{ run.progress }}%</span>
            </td>
            <td class="px-3 py-3">
              {{ formatPct(run.summary.totalReturnPct) }}
            </td>
            <td class="px-3 py-3">
              {{ formatPct(run.summary.benchmarkReturnPct) }}
            </td>
            <td class="px-3 py-3">
              {{ run.summary.tradeCount ?? '—' }}
            </td>
            <td class="px-3 py-3">
              <div class="flex gap-2">
                <RouterLink
                  :to="`/market/backtests/${run.id}`"
                  class="text-primary hover:underline"
                >
                  查看结果
                </RouterLink>
                <RouterLink
                  v-if="run.taskId"
                  :to="`/tasks/runs?taskId=${run.taskId}`"
                  class="text-secondary-text hover:text-primary"
                >
                  任务
                </RouterLink>
                <button
                  type="button"
                  class="text-secondary-text hover:text-primary"
                  @click="emit('reuse', run)"
                >
                  复用
                </button>
              </div>
              <p
                v-if="run.status === 'failed' && run.error"
                class="mt-1 max-w-xs truncate text-danger"
                :title="run.error"
              >
                {{ run.error }}
              </p>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
