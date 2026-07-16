<script setup lang="ts">
import type { RealtimeTrend, TrendDirection } from '@/api/realtimeMarket';
import Tooltip from '@/components/common/Tooltip.vue';
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
  if (!usable.value || !trend) return 'bg-muted-text';
  if (trend.state === 'neutral' || trend.streak < 2) return 'bg-amber-500';
  return trend.state === 'above' ? 'bg-red-500' : 'bg-emerald-500';
});

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

const tooltip = computed(() => {
  const trend = props.trend;
  if (!trend) return '1分钟滚动均线\n数据不足';
  const lines = [
    '1分钟滚动均线',
    `当前周期：${trend.effective_period} / 目标周期：${trend.target_period}`,
  ];
  if (finite(trend.ma_value)) lines.push(`均线：${trend.ma_value.toFixed(2)}`);
  if (finite(trend.close)) lines.push(`收盘价：${trend.close.toFixed(2)}`);
  if (finite(trend.distance_pct)) {
    lines.push(`偏离：${trend.distance_pct > 0 ? '+' : ''}${trend.distance_pct.toFixed(2)}%`);
  }
  lines.push(`方向：${directionText[trend.state]}`);
  if (trend.state !== 'insufficient') lines.push(`连续：${trend.streak}`);
  if (trend.bar_time) {
    const formatted = formatDateTimeInDisplayTimezone(trend.bar_time);
    if (formatted !== '—' && formatted !== trend.bar_time) lines.push(`K线时间：${formatted}`);
  }
  if (trend.trading_date) lines.push(`交易日：${trend.trading_date}`);
  if (trend.trade_session) lines.push(`交易时段：${trend.trade_session}`);
  return lines.join('\n');
});
</script>

<template>
  <Tooltip
    :content="tooltip"
    content-class="whitespace-pre-line"
    focusable
  >
    <span class="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-foreground">
      <span
        data-testid="trend-dot"
        class="h-2.5 w-2.5 shrink-0 rounded-full"
        :class="dotClass"
      />
      <span>{{ label }}</span>
    </span>
  </Tooltip>
</template>
