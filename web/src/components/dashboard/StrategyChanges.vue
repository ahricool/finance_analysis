<script setup lang="ts">
import type { ETFRankingResponse } from '@/types/etfRotation';
import type { TrendRankingResponse } from '@/types/trendFollowing';
import { computed } from 'vue';
import { etfHighlights, regimeText, regimeTone, trendHighlights } from './dashboardFormat';
const props = defineProps<{ etf?: ETFRankingResponse | null; trend?: TrendRankingResponse | null }>();
const changes = computed(() => props.etf?.changes ?? props.trend?.changes);
const rows = computed(() => props.etf ? etfHighlights(props.etf.changes) : trendHighlights(props.trend?.changes).slice(0, 3));
const regime = computed(() => props.etf?.marketSnapshot?.regime ?? props.trend?.marketRegime);
const counts = computed(() => props.etf ? [
  ['新增 BUY', props.etf.changes?.newBuys.length ?? 0], ['新增 EXIT', props.etf.changes?.newExits.length ?? 0],
  ['排名变化', props.etf.changes?.rankMovers.length ?? 0],
] : ['ENTRY', 'ADD', 'WEAKENING', 'REDUCE', 'EXIT'].map(action => [action, trendHighlights(props.trend?.changes).filter(row =>
  action === 'WEAKENING' ? row.currentState === action : row.currentAction === action).length]));
</script>

<template>
  <div class="mb-3 flex items-center justify-between gap-2 text-xs">
    <span class="text-muted-foreground">{{ etf?.tradeDate ?? trend?.tradeDate }} <template v-if="changes?.previousTradeDate">较 {{ changes.previousTradeDate }}</template></span>
    <span :class="regimeTone(regime)">{{ regimeText(regime) }}</span>
  </div>
  <template v-if="changes?.previousTradeDate">
    <div class="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span
        v-for="[label, count] in counts"
        :key="label"
      >{{ label }} <strong class="ml-1 text-foreground">{{ count }}</strong></span>
    </div>
    <div
      v-for="row in rows"
      :key="row.code"
      class="flex justify-between gap-2 py-1.5 text-sm"
    >
      <span class="truncate font-medium">{{ row.name || row.code }}</span>
      <span class="shrink-0 text-xs text-muted-foreground">{{ row.currentState === 'WEAKENING' ? row.previousState : row.previousAction ?? '—' }} → <strong :class="['EXIT', 'REDUCE'].includes(row.currentAction ?? '') ? 'text-market-down' : 'text-foreground'">{{ row.currentState === 'WEAKENING' ? row.currentState : row.currentAction }}</strong></span>
    </div>
    <p
      v-if="!rows.length"
      class="text-sm text-muted-foreground"
    >
      暂无重点行动变化
    </p>
  </template>
  <p
    v-else
    class="text-sm text-muted-foreground"
  >
    暂无上一交易日对比数据
  </p>
</template>
