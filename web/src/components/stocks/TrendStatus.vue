<script setup lang="ts">
import type { RealtimeTrend, TrendDirection } from '@/api/realtimeMarket';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { computed } from 'vue';

const props = defineProps<{
  trend?: RealtimeTrend | null;
}>();

const usable = computed(
  () => props.trend && props.trend.state !== 'insufficient' && props.trend.streak > 0,
);

const directionText: Record<TrendDirection, string> = {
  above: '多',
  below: '空',
  neutral: '中',
  insufficient: '数据不足',
};

const label = computed(() => {
  if (!usable.value || !props.trend) return '数据不足';
  return `${directionText[props.trend.state]} ${props.trend.streak}`;
});

const dotClass = computed(() => {
  const trend = props.trend;
  if (!usable.value || !trend) return 'bg-muted-foreground';
  if (trend.state === 'neutral' || trend.streak < 2) return 'bg-warning';
  return trend.state === 'above' ? 'bg-market-up' : 'bg-market-down';
});

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

const tooltip = computed(() => {
  const trend = props.trend;
  if (!trend) return '1分钟滚动均线\n数据不足';
  const lines = [
    '1分钟滚动均线',
    `当前周期：${trend.effectivePeriod} / 目标周期：${trend.targetPeriod}`,
  ];
  if (finite(trend.maValue)) lines.push(`均线：${trend.maValue.toFixed(2)}`);
  if (finite(trend.close)) lines.push(`收盘价：${trend.close.toFixed(2)}`);
  if (finite(trend.distancePct)) {
    lines.push(`偏离：${trend.distancePct > 0 ? '+' : ''}${trend.distancePct.toFixed(2)}%`);
  }
  lines.push(`方向：${directionText[trend.state]}`);
  if (trend.state !== 'insufficient') lines.push(`连续：${trend.streak}`);
  if (trend.barTime) {
    const formatted = formatDateTimeInDisplayTimezone(trend.barTime);
    if (formatted !== '—' && formatted !== trend.barTime) lines.push(`K线时间：${formatted}`);
  }
  if (trend.tradingDate) lines.push(`交易日：${trend.tradingDate}`);
  if (trend.tradeSession) lines.push(`交易时段：${trend.tradeSession}`);
  return lines.join('\n');
});
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          tabindex="0"
          class="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-foreground"
        >
          <span
            data-testid="trend-dot"
            class="h-2.5 w-2.5 shrink-0 rounded-full"
            :class="dotClass"
          />
          <span>{{ label }}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent class="whitespace-pre-line">
        {{ tooltip }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
