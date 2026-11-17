<script setup lang="ts">
import type { IntradayOpportunities, SimulationPlan } from '@/api/intradayOptions';
import { clock, directions, fmt, opportunityKinds, opportunityStates, confirmationLabel } from './labels';
defineProps<{ opportunities?: IntradayOpportunities | null; stale: boolean; plans?: SimulationPlan[] }>();
</script>

<template>
  <section
    class="space-y-2 rounded border p-3"
    data-testid="opportunity-detail"
  >
    <p class="text-sm font-medium">
      日内机会 · 确认状态与形态质量分开
    </p>
    <p
      v-if="stale"
      class="text-xs text-amber-600 dark:text-amber-400"
    >
      以下为历史/参考结果，不列为当前有效机会。
    </p>
    <p
      v-for="reason in opportunities?.reasons ?? ['等待机会数据']"
      :key="reason"
      class="text-xs text-muted-foreground"
    >
      {{ reason }}
    </p>
    <div class="grid gap-2 lg:grid-cols-3">
      <article
        v-for="branch in opportunities?.branches ?? []"
        :key="branch.structureId"
        class="space-y-1 rounded border p-2 text-xs"
      >
        <p class="font-medium">
          {{ opportunityKinds[branch.kind] }} · {{ directions[branch.direction] }}
        </p>
        <p>{{ opportunityStates[branch.status] }}{{ opportunities?.reference || stale ? '（参考）' : '' }} · 分支质量 {{ fmt(branch.qualityScore) }}</p>
        <p>{{ confirmationLabel(branch.confirmationMethod) }} · 形态确认不等于当前可进场</p>
        <p
          v-if="!stale"
          class="font-medium"
        >
          {{ plans?.find(p => p.structureId === branch.structureId)?.executionReason ?? '等待实时报价执行检查' }}
        </p>
        <p
          v-if="branch.supersededBy"
          class="text-muted-foreground"
        >
          已有后续独立结构，保留原证据
        </p>
        <p v-if="branch.structureStart">
          结构 {{ clock(branch.structureStart) }}–{{ clock(branch.structureEnd) }} · {{ fmt(branch.structureLow, 2) }}–{{ fmt(branch.structureHigh, 2) }}
        </p>
        <p v-if="branch.atrSource === 'observed_adjacent_true_ranges'">
          波动尺度 {{ fmt(branch.atr, 3) }} · {{ branch.atrSamples }} 个真实相邻波动样本
        </p>
        <p>固定触发位 {{ fmt(branch.trigger, 2) }} · 失效位 {{ fmt(branch.invalidation, 2) }}</p>
        <p>距触发位 {{ fmt(branch.distanceAtr, 2) }} ATR · 距失效位 {{ fmt(branch.riskAtr, 2) }} ATR</p>
        <p>背景起点 {{ clock(branch.formationStart) }} · 候选形成 {{ clock(branch.startedAt) }} · 突破 {{ clock(branch.triggeredAt) }}</p>
        <p>首次确认 {{ clock(branch.confirmedAt) }} · 到期 {{ clock(branch.expiresAt) }}</p>
        <p>结构 {{ fmt(branch.components.structure) }} · 距离 {{ fmt(branch.components.distance) }} · 恢复 {{ fmt(branch.components.recovery) }} · 失效距离 {{ fmt(branch.components.risk) }}</p>
        <p
          v-for="reason in branch.reasons"
          :key="reason"
          class="text-muted-foreground"
        >
          {{ reason }}
        </p>
      </article>
    </div>
    <p class="text-xs text-muted-foreground">
      分支质量：结构25% / 触发距离35% / 恢复25% / 失效距离15%；仅已确认且未延伸分支参与有效机会排序。
      做多/做空使用镜像规则；阈值尚未收益校准。只分析标的价格，不选择合约，不代表期权收益或成交保证。
    </p>
  </section>
</template>
