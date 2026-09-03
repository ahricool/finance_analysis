<script setup lang="ts">
import type {
  PatternDirection,
  PatternStage,
  RealtimePatternSignal,
  RealtimePatternState,
} from '@/api/realtimeMarket';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { formatDateTimeInDisplayTimezone, getDisplayTimezone } from '@/utils/format';
import { computed } from 'vue';

const props = defineProps<{
  pattern?: RealtimePatternState | null;
  now?: Date;
}>();

const signal = computed<RealtimePatternSignal | null>(() =>
  props.pattern?.status === 'active' ? (props.pattern.signal ?? null) : null,
);
const previewSignal = computed<RealtimePatternSignal | null>(() =>
  props.pattern?.preview_status === 'active' ? (props.pattern.preview_signal ?? null) : null,
);

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
  warning: '观察',
  confirmed: '已确认',
};

function primaryLabel(value: RealtimePatternSignal): string {
  if (value.direction === 'neutral_wait') return '等待方向';
  const labels: Record<
    Exclude<PatternDirection, 'neutral_wait'>,
    { warning: string; confirmed: string; forming: string }
  > = {
    bullish_continuation: { forming: '多头整理', warning: '向上突破预警', confirmed: '多延续确认' },
    bearish_continuation: { forming: '空头整理', warning: '向下突破预警', confirmed: '空延续确认' },
    bearish_to_bullish: { forming: '空转多形成中', warning: '空转多预警', confirmed: '空转多确认' },
    bullish_to_bearish: { forming: '多转空形成中', warning: '多转空预警', confirmed: '多转空确认' },
    bullish_breakout: { forming: '向上突破形成中', warning: '向上突破预警', confirmed: '向上突破' },
    bearish_breakout: { forming: '向下突破形成中', warning: '向下突破预警', confirmed: '向下突破' },
  };
  return labels[value.direction][value.stage];
}

function timezoneParts(date: Date): Record<string, string> {
  return Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: getDisplayTimezone(),
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
}

function dateKey(parts: Record<string, string>): string {
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function previousDateKey(parts: Record<string, string>): string {
  const date = new Date(
    Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day) - 1),
  );
  return date.toISOString().slice(0, 10);
}

function eventTime(value: RealtimePatternSignal): Date | null {
  const raw =
    value.stage === 'confirmed' && value.confirmed_at ? value.confirmed_at : value.occurred_at;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function ageText(value: RealtimePatternSignal): string {
  const event = eventTime(value);
  if (!event) return '时间未知';

  const current = props.now ?? new Date();
  const elapsedMinutes = Math.max(0, (current.getTime() - event.getTime()) / 60_000);
  if (elapsedMinutes < 1) return '刚刚';
  if (elapsedMinutes < 60) return `${Math.floor(elapsedMinutes)}分钟前`;
  if (elapsedMinutes < 24 * 60) return `${Math.floor(elapsedMinutes / 60)}小时前`;

  const currentParts = timezoneParts(current);
  const eventParts = timezoneParts(event);
  const time = `${eventParts.hour}:${eventParts.minute}`;
  if (dateKey(eventParts) === dateKey(currentParts)) return `今日 ${time}`;
  if (dateKey(eventParts) === previousDateKey(currentParts)) return `昨日 ${time}`;
  return `${eventParts.month}-${eventParts.day} ${time}`;
}

const emptyTitle = computed(() => {
  if (signal.value || previewSignal.value) return '';
  if (props.pattern?.status === 'insufficient' || !props.pattern) return '数据不足';
  return '暂无近期形态';
});

const detail = computed(() =>
  signal.value
    ? `${stageText[signal.value.stage]} · ${signal.value.quality_score}分 · ${ageText(signal.value)}`
    : '',
);

const invalidationText = computed(() =>
  finite(signal.value?.invalidation_price)
    ? `失效：${signal.value.invalidation_price.toFixed(2)}`
    : '',
);

const formalColorClass = computed(() => {
  const value = signal.value;
  if (!value) return 'text-muted-foreground';
  if (value.direction === 'neutral_wait' || value.stage === 'forming') return 'text-amber-500';
  if (
    ['bullish_continuation', 'bearish_to_bullish', 'bullish_breakout'].includes(value.direction)
  ) {
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
  const lines: string[] = [];
  const formal = signal.value;
  const preview = previewSignal.value;
  if (formal) {
    lines.push('【正式形态】');
    lines.push(
      `形态名称：${formal.pattern_name}`,
      `方向含义：${directionMeaning[formal.direction]}`,
      `当前阶段：${stageText[formal.stage]}`,
      `形态质量分：${formal.quality_score} / 100`,
      '判断理由：',
      ...formal.reasons.map((reason) => `- ${reason}`),
    );
    if (finite(formal.reference_level))
      lines.push(`参考价位：${formal.reference_level.toFixed(2)}`);
    if (finite(formal.invalidation_price))
      lines.push(`失效价位：${formal.invalidation_price.toFixed(2)}`);
    lines.push(`形态开始时间：${formatTime(formal.occurred_at)}`);
    lines.push(`确认时间：${formatTime(formal.confirmed_at)}`);
    lines.push(`K线数量差：${formal.bars_ago} 根`);
    lines.push(`交易时段分钟差：${formal.session_minutes_ago} 分钟`);
    if (formal.trading_date) lines.push(`交易日：${formal.trading_date}`);
    if (formal.trade_session) lines.push(`交易时段：${formal.trade_session}`);
  } else {
    lines.push('【正式形态】', props.pattern?.status === 'none' ? '暂无近期形态' : '数据不足');
  }
  if (preview) {
    if (lines.length) lines.push('');
    lines.push(
      '【实时预览 · 当前一分钟K线未收盘】',
      `形态名称：${preview.pattern_name}`,
      `方向含义：${directionMeaning[preview.direction]}`,
      `当前阶段：${stageText[preview.stage]}`,
      `形态质量分：${preview.quality_score} / 100`,
      '判断理由：',
      ...preview.reasons.map((reason) => `- ${reason}`),
    );
    if (finite(preview.reference_level))
      lines.push(`参考价位：${preview.reference_level.toFixed(2)}`);
    if (finite(preview.invalidation_price))
      lines.push(`失效价位：${preview.invalidation_price.toFixed(2)}`);
    if (finite(props.pattern?.preview_price))
      lines.push(`当前预览价格：${props.pattern.preview_price.toFixed(2)}`);
    lines.push(`当前K线时间：${formatTime(props.pattern?.preview_bar_time)}`);
    lines.push(`预览更新时间：${formatTime(props.pattern?.preview_updated_at)}`);
    lines.push('说明：一分钟K线尚未收盘，信号可能变化，不作为正式确认信号');
  }
  return lines.join('\n');
});
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          tabindex="0"
          class="flex min-w-0 flex-col gap-0.5 text-xs leading-tight"
        >
          <span
            v-if="signal"
            class="whitespace-nowrap font-semibold"
            :class="formalColorClass"
          >正式 · {{ primaryLabel(signal) }}</span>
          <span
            v-if="signal && !previewSignal && detail"
            class="whitespace-nowrap text-xs text-muted-foreground"
          >
            {{ detail }}
          </span>
          <span
            v-if="signal && !previewSignal && invalidationText"
            class="whitespace-nowrap text-xs text-muted-foreground"
          >
            {{ invalidationText }}
          </span>
          <span
            v-if="previewSignal"
            class="whitespace-nowrap font-semibold text-amber-500"
          >实时预览 · {{ primaryLabel(previewSignal) }} · 未收盘</span>
          <span
            v-if="previewSignal && !signal"
            class="whitespace-nowrap text-xs text-warning"
          >{{ stageText[previewSignal.stage] }} · {{ previewSignal.quality_score }}分 · 可能变化</span>
          <span
            v-if="emptyTitle"
            class="whitespace-nowrap font-semibold text-muted-foreground"
          >{{
            emptyTitle
          }}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent
        side="left"
        class="max-w-[min(32rem,calc(100vw-1rem))] whitespace-pre-line"
      >
        {{ tooltip }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
