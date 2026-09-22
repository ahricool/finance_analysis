<script setup lang="ts">
import type { SignalEvaluation } from '@/api/signalCenter';
import { formatRealizedReturn } from '@/utils/quant';
import { formatDateTime } from '@/utils/format';
import { horizonText, returnClass } from './evaluation';
defineProps<{ evaluation: SignalEvaluation }>();
const states = { pending: '等待首日收盘', partial: '持续观察', complete: '10日观察完成', unavailable: '暂不可评估', not_applicable: '不适用' };
</script>

<template>
  <section
    class="space-y-2 border-t pt-3 text-sm"
    data-testid="signal-evaluation"
  >
    <h4 class="font-semibold">
      收益回看 · {{ states[evaluation.status] }}
    </h4>
    <p class="text-xs text-muted-foreground">
      基准：{{ evaluation.entryDate || '待确定' }} 开盘 {{ evaluation.entryPrice?.toFixed(2) ?? '—' }}（前复权）
      · 已观察 {{ evaluation.observedSessions }}/10 个交易日 · 行情截至 {{ evaluation.asOf || '—' }}
    </p>
    <div class="grid grid-cols-4 gap-2">
      <div
        v-for="days in [1, 3, 5, 10]"
        :key="days"
        class="rounded border p-2"
      >
        <p class="text-xs text-muted-foreground">
          {{ days }}D 收益
        </p>
        <p :class="returnClass(evaluation.horizons.find(h => h.days === days)?.value)">
          {{ horizonText(evaluation, days) }}
        </p>
        <p class="text-xs text-muted-foreground">
          {{ evaluation.horizons.find(h => h.days === days)?.targetDate || '—' }}
        </p>
      </div>
    </div>
    <div class="grid grid-cols-3 gap-2">
      <p>最大有利变动 <span :class="returnClass(evaluation.mfe)">{{ formatRealizedReturn(evaluation.mfe) }}</span></p>
      <p>最大不利变动 <span :class="returnClass(evaluation.mae)">{{ formatRealizedReturn(evaluation.mae) }}</span></p>
      <p>收盘最大回撤 <span :class="returnClass(evaluation.maxDrawdownClose)">{{ formatRealizedReturn(evaluation.maxDrawdownClose) }}</span></p>
    </div>
    <p
      v-if="evaluation.missingDates.length"
      class="text-xs text-muted-foreground"
    >
      缺失或无效行情：{{ evaluation.missingDates.join('、') }}；不补零、不用后续日期替代。
    </p>
    <p
      v-if="evaluation.status === 'unavailable' && !evaluation.entryDate"
      class="text-xs text-muted-foreground"
    >
      交易日历或信号完成时间不可用，无法确定可交易基准。
    </p>
    <p class="text-xs text-muted-foreground">
      以实际生成后的首个交易日开盘为模拟基准；第1日是该日收盘。变动与回撤仅覆盖已观察的前10个交易日，缺日不计算区间极值。收盘回撤从基准及后续收盘高点计算。
    </p>
    <p class="text-xs text-muted-foreground">
      这是价格表现，不是实际成交收益；未计手续费、滑点及涨跌停成交限制，A股1D仅作观察，不代表可当日卖出。计算时间：{{ formatDateTime(evaluation.evaluatedAt) }}
    </p>
  </section>
</template>
