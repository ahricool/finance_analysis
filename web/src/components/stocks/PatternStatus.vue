<script setup lang="ts">
import type {
  PatternDirection,
  PatternStage,
  RealtimePatternSignal,
  RealtimePatternState,
} from '@/api/realtimeMarket';
import Tooltip from '@/components/common/Tooltip.vue';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { computed } from 'vue';

const props = defineProps<{
  pattern?: RealtimePatternState | null;
}>();

const signal = computed<RealtimePatternSignal | null>(() => (
  props.pattern?.status === 'active' ? props.pattern.signal ?? null : null
));

const directionMeaning: Record<PatternDirection, string> = {
  bullish_continuation: '多头趋势延续',
  bearish_continuation: '空头趋势延续',
  bearish_to_bullish: '空头结构向多头切换',
  bullish_to_bearish: '多头结构向空头切换',
  bullish_breakout: '向上扩张突破',
  bearish_breakout: '向下扩张突破',
  neutral_wait: '波动收缩，等待方向选择',
};

const stageText: Record<PatternStage, string> = {
  forming: '形成中',
  warning: '预警',
  confirmed: '确认',
};

function primaryLabel(value: RealtimePatternSignal): string {
  if (value.direction === 'neutral_wait') return '等待方向';
  const labels: Record<Exclude<PatternDirection, 'neutral_wait'>, { warning: string; confirmed: string; forming: string }> = {
    bullish_continuation: { forming: '多头整理', warning: '向上突破预警', confirmed: '多延续确认' },
    bearish_continuation: { forming: '空头整理', warning: '向下突破预警', confirmed: '空延续确认' },
    bearish_to_bullish: { forming: '空转多形成中', warning: '空转多预警', confirmed: '空转多确认' },
    bullish_to_bearish: { forming: '多转空形成中', warning: '多转空预警', confirmed: '多转空确认' },
    bullish_breakout: { forming: '向上突破形成中', warning: '向上突破预警', confirmed: '向上突破' },
    bearish_breakout: { forming: '向下突破形成中', warning: '向下突破预警', confirmed: '向下突破' },
  };
  return labels[value.direction][value.stage];
}

function ageText(value: RealtimePatternSignal): string {
  if (value.stage === 'forming' && value.direction === 'neutral_wait') return '持续中';
  if (value.bars_ago === 0) return '刚刚';
  if (value.bars_ago === 1) return '1分钟前';
  return `${value.bars_ago}分钟前`;
}

const title = computed(() => {
  if (props.pattern?.status === 'insufficient' || !props.pattern) return '数据不足';
  if (!signal.value) return '暂无近期形态';
  return primaryLabel(signal.value);
});

const detail = computed(() => (
  signal.value ? `${signal.value.pattern_name} · ${ageText(signal.value)}` : ''
));

const colorClass = computed(() => {
  const value = signal.value;
  if (!value) return 'text-muted-text';
  if (value.direction === 'neutral_wait' || value.stage === 'forming') return 'text-amber-500';
  if (['bullish_continuation', 'bearish_to_bullish', 'bullish_breakout'].includes(value.direction)) {
    return 'text-red-500';
  }
  return 'text-emerald-500';
});

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  const formatted = formatDateTimeInDisplayTimezone(value);
  return formatted === value ? '—' : formatted;
}

const tooltip = computed(() => {
  const value = signal.value;
  if (!value) return props.pattern?.status === 'none' ? '1分钟多K线价格行为\n暂无近期形态' : '1分钟多K线价格行为\n数据不足';
  const lines = [
    `形态名称：${value.pattern_name}`,
    `方向含义：${directionMeaning[value.direction]}`,
    `当前阶段：${stageText[value.stage]}`,
    `形态质量分：${value.quality_score} / 100`,
    '判断理由：',
    ...value.reasons.map((reason) => `- ${reason}`),
  ];
  if (finite(value.reference_level)) lines.push(`参考价位：${value.reference_level.toFixed(2)}`);
  if (finite(value.invalidation_price)) lines.push(`失效价位：${value.invalidation_price.toFixed(2)}`);
  lines.push(`形态开始时间：${formatTime(value.occurred_at)}`);
  lines.push(`确认时间：${formatTime(value.confirmed_at)}`);
  lines.push(`K线数量差：${value.bars_ago} 根`);
  lines.push(`交易时段分钟差：${value.session_minutes_ago} 分钟`);
  if (value.trading_date) lines.push(`交易日：${value.trading_date}`);
  if (value.trade_session) lines.push(`交易时段：${value.trade_session}`);
  return lines.join('\n');
});
</script>

<template>
  <Tooltip
    :content="tooltip"
    content-class="whitespace-pre-line"
    focusable
  >
    <span class="flex min-w-0 flex-col gap-0.5 text-xs" :class="colorClass">
      <span class="whitespace-nowrap font-semibold">{{ title }}</span>
      <span v-if="detail" class="max-w-[180px] truncate whitespace-nowrap text-[11px] text-secondary-text">
        {{ detail }}
      </span>
    </span>
  </Tooltip>
</template>
