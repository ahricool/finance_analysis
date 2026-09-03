<script setup lang="ts">
import type { RealtimeQuote } from '@/api/realtimeMarket';
import type { MarketType } from '@/api/watchList';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { calculateZeroDteStatus } from '@/utils/zeroDteStatus';
import { ArrowDownRight, ArrowUpRight, Clock3, Minus, ShieldX } from 'lucide-vue-next';
import { computed } from 'vue';

const props = defineProps<{
  quote?: RealtimeQuote | null;
  marketType: MarketType;
  now?: Date;
}>();

const result = computed(() => calculateZeroDteStatus(props.quote, props.marketType, props.now));

const appearance = computed(() => {
  switch (result.value?.status) {
    case 'CALL确认':
      return {
        className: 'border-red-500/35 bg-red-500/12 text-red-600 dark:text-red-400',
        icon: ArrowUpRight,
      };
    case 'CALL观察':
      return { className: 'border-red-400/25 bg-red-500/7 text-red-500', icon: ArrowUpRight };
    case 'CALL延续':
      return { className: 'border-red-400/20 bg-red-500/5 text-red-500/80', icon: ArrowUpRight };
    case 'PUT确认':
      return {
        className: 'border-emerald-500/35 bg-emerald-500/12 text-emerald-600 dark:text-emerald-400',
        icon: ArrowDownRight,
      };
    case 'PUT观察':
      return {
        className: 'border-emerald-400/25 bg-emerald-500/7 text-emerald-500',
        icon: ArrowDownRight,
      };
    case 'PUT延续':
      return {
        className: 'border-emerald-400/20 bg-emerald-500/5 text-emerald-500/80',
        icon: ArrowDownRight,
      };
    case '已经失效':
      return {
        className: 'border-amber-500/35 bg-amber-500/10 text-amber-600 dark:text-amber-400',
        icon: ShieldX,
      };
    case '信号过期':
    case '当日已收盘':
    case '上个交易日信号':
      return { className: 'border-border bg-muted/35 text-muted-foreground', icon: Clock3 };
    default:
      return { className: 'border-border bg-background text-muted-foreground', icon: Minus };
  }
});

const helper = computed(() => {
  if (result.value?.status === 'CALL延续') return '不宜追高';
  if (result.value?.status === 'PUT延续') return '不宜追空';
  return '';
});

const tooltip = computed(() => {
  if (!result.value) return '仅美股且实时行情、趋势与形态数据完整时计算。';
  const lines = [
    result.value.reason,
    result.value.ageMinutes === null ? '' : `形态真实年龄：${result.value.ageMinutes} 分钟`,
    '该状态反映标的当前一分钟趋势和形态，不代表自动交易或强制持仓指令。',
  ];
  return lines.filter(Boolean).join('\n');
});
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          tabindex="0"
          :class="result
            ? 'inline-flex min-w-0 flex-col items-start gap-0.5'
            : 'text-xs text-muted-foreground'"
        >
          <template v-if="result">
            <span
              class="inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-1 text-xs font-semibold leading-none"
              :class="appearance.className"
            >
              <component
                :is="appearance.icon"
                class="h-3.5 w-3.5 shrink-0"
                aria-hidden="true"
              />
              {{ result.status }}
            </span>
            <span
              v-if="helper"
              class="whitespace-nowrap text-xs text-muted-foreground"
            >{{
              helper
            }}</span>
          </template>
          <template v-else>—</template>
        </span>
      </TooltipTrigger>
      <TooltipContent class="whitespace-pre-line">
        {{ tooltip }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
