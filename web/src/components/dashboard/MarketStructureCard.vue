<script setup lang="ts">
import { computed } from 'vue';
import type { MarketStructureSnapshot } from '@/api/marketStructure';
import { formatPercent, formatScore } from '@/utils/quant';
const props = defineProps<{ snapshot: MarketStructureSnapshot }>();
const stateNames: Record<string, string> = {
  BROAD_STRENGTH: '广泛走强', NORMAL: '正常', MILD_DIVERGENCE: '轻度背离', STRONG_DIVERGENCE: '指数明显强于成分股',
  STABLE: '排名稳定', FAST: '快速轮动', EXTREME: '剧烈轮动',
};
const metrics = computed(() => [
  { name: 'Breadth Divergence', value: formatPercent(props.snapshot.breadth.breadthDivergence5D),
    state: stateNames[props.snapshot.metrics.states.breadth],
    explanation: '5D 基准收益 − 成分股收益中位数；正值越高，指数领先普通股票越明显。' },
  { name: 'Rotation Velocity', value: `${formatScore(props.snapshot.rotation.rotationVelocity3D)} / 100`,
    state: stateNames[props.snapshot.metrics.states.rotation ?? ''] ?? '历史不足或成员变化',
    explanation: 'ETF 综合排名与第 3 个历史快照日比较：0 稳定，50 明显轮动，100 完全反转。' },
  { name: 'Leadership Concentration', value: formatPercent(props.snapshot.leadership.leadershipConcentration5D),
    state: 'Top 10% · 5D', explanation: '收益领先的前 10% 股票，占全体正收益之和的比例；并非市值加权的指数贡献。' },
  { name: 'Leadership HHI', value: `${formatScore(props.snapshot.leadership.leadershipHhi5D)} / 100`,
    state: '5D · 按样本数归一化', explanation: '正收益份额的平方和归一化到 0–100。均匀上涨为 0，单只股票贡献全部上涨为 100。' },
]);
</script>

<template>
  <div class="space-y-3">
    <div class="flex justify-between text-sm">
      <strong>市场结构 · {{ snapshot.market }}</strong>
      <span class="text-muted-foreground">{{ snapshot.tradeDate }}</span>
    </div>
    <p
      v-if="snapshot.tradeDate < snapshot.expectedTradeDate"
      class="text-sm text-muted-foreground"
    >
      暂无今日市场结构数据 · 以下为最近正式快照
    </p>
    <div class="grid grid-cols-2 gap-4">
      <details
        v-for="metric in metrics"
        :key="metric.name"
        class="rounded-md border p-3"
      >
        <summary class="cursor-pointer text-xs text-muted-foreground">
          {{ metric.name }}
          <strong class="my-2 block text-xl tabular-nums text-foreground">{{ metric.value }}</strong>
          <span>{{ metric.state }}</span>
        </summary>
        <p class="mt-3 text-xs leading-5 text-muted-foreground">
          {{ metric.explanation }}
        </p>
      </details>
    </div>
    <details class="text-xs text-muted-foreground">
      <summary class="cursor-pointer">
        范围与广度明细
      </summary>
      <p class="mt-2 leading-6">
        {{ snapshot.metrics.universeKey }} · {{ snapshot.metrics.memberCount }}/{{ snapshot.metrics.universeSize }} 只
        · 覆盖率 {{ formatPercent(snapshot.metrics.dataCoverage) }} · 基准 {{ snapshot.metrics.benchmarkCode }}<br>
        基准 5D {{ formatPercent(snapshot.breadth.benchmarkReturn5D) }} · 中位数 {{ formatPercent(snapshot.breadth.medianMemberReturn5D) }}<br>
        5D 上涨占比 {{ formatPercent(snapshot.breadth.memberPositiveRatio5D) }} · MA10 以上 {{ formatPercent(snapshot.breadth.memberAboveMa10Ratio) }} · MA20 以上 {{ formatPercent(snapshot.breadth.memberAboveMa20Ratio) }}
      </p>
    </details>
  </div>
</template>
