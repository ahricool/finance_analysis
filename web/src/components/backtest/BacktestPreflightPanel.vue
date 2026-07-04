<script setup lang="ts">
import type { BacktestPreflight } from '@/types/backtests';
import { engineLabels, marketLabels } from '@/utils/backtests';

defineProps<{ result: BacktestPreflight }>();
</script>

<template>
  <section
    class="rounded-2xl border p-4"
    :class="result.ready ? 'border-success/40 bg-success/5' : 'border-danger/40 bg-danger/5'"
    data-testid="backtest-preflight"
  >
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-semibold text-foreground">
        数据检查
      </h3>
      <span
        class="text-sm font-medium"
        :class="result.ready ? 'text-success' : 'text-danger'"
      >
        {{ result.ready ? '可以回测' : '暂不可回测' }}
      </span>
    </div>
    <dl class="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
      <div>
        <dt class="text-muted-text">
          引擎
        </dt><dd>{{ engineLabels[result.engine] }} {{ result.engineVersion }}</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          市场 / 标的
        </dt><dd>{{ marketLabels[result.market] }} · {{ result.code }}</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          数据范围
        </dt><dd>{{ result.availableDateFrom || '—' }} 至 {{ result.availableDateTo || '—' }}</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          覆盖率
        </dt><dd>{{ (result.coverageRatio * 100).toFixed(2) }}%</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          请求交易日
        </dt><dd>{{ result.requestedTradingDays }}</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          实际交易日
        </dt><dd>{{ result.availableTradingDays }}</dd>
      </div>
      <div>
        <dt class="text-muted-text">
          预热交易日
        </dt><dd>{{ result.warmupDays }}</dd>
      </div>
    </dl>
    <ul
      v-if="result.errors.length"
      class="mt-3 list-disc space-y-1 pl-5 text-xs text-danger"
    >
      <li
        v-for="item in result.errors"
        :key="item"
      >
        {{ item }}
      </li>
    </ul>
    <ul
      v-if="result.warnings.length"
      class="mt-3 list-disc space-y-1 pl-5 text-xs text-warning"
    >
      <li
        v-for="item in result.warnings"
        :key="item"
      >
        {{ item }}
      </li>
    </ul>
  </section>
</template>
