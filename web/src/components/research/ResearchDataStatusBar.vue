<script setup lang="ts">
import { computed } from 'vue';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useCurrentTime } from '@/composables/useCurrentTime';
import {
  formatCompactDateTimeInDisplayTimezone,
  formatFullDateTimeWithTimezone,
  formatRelativeAge,
} from '@/utils/format';
import {
  isPreviewCompleted,
  previewProviderLabel,
  type ResearchDataMode,
} from '@/utils/researchPreview';

const props = defineProps<{
  mode: ResearchDataMode;
  tradeDate?: string | null;
  dataAsOf?: string | null;
  previewTime?: string | null;
  generatedAt?: string | null;
  provider?: string | null;
  officialTradeDate?: string | null;
  previewStatus?: string | null;
  reason?: string | null;
}>();

const now = useCurrentTime();
const previewUsable = computed(() => props.mode === 'preview' && isPreviewCompleted(props.previewStatus));
const previewUnavailable = computed(() => props.mode === 'preview' && !isPreviewCompleted(props.previewStatus));
const ageSource = computed(() => props.dataAsOf || props.previewTime);
const ageUsesFallback = computed(() => props.mode === 'preview' && !props.dataAsOf && Boolean(props.previewTime));

const fields = computed(() => {
  if (props.mode === 'official') {
    return [
      { label: '数据有效至', value: props.tradeDate ? `${props.tradeDate} 收盘` : '—', title: props.tradeDate || undefined },
      { label: '快照生成', value: formatCompactDateTimeInDisplayTimezone(props.generatedAt, now.value), title: formatFullDateTimeWithTimezone(props.generatedAt) },
      { label: '对应交易日', value: props.tradeDate || '—', testid: 'research-trade-date' },
    ];
  }
  if (previewUnavailable.value) {
    return [
      { label: '生成时间', value: formatCompactDateTimeInDisplayTimezone(props.previewTime, now.value), title: formatFullDateTimeWithTimezone(props.previewTime) },
      { label: '数据源', value: previewProviderLabel(props.provider), testid: 'research-provider' },
      { label: '原因', value: props.reason || '预演未完成', testid: 'research-preview-reason' },
    ];
  }
  return [
    {
      label: '数据有效至',
      value: formatCompactDateTimeInDisplayTimezone(props.dataAsOf, now.value),
      title: formatFullDateTimeWithTimezone(props.dataAsOf),
      testid: 'research-data-as-of',
    },
    {
      label: 'Preview 生成',
      value: formatCompactDateTimeInDisplayTimezone(props.previewTime, now.value),
      title: formatFullDateTimeWithTimezone(props.previewTime),
      testid: 'research-preview-time',
    },
    {
      label: ageUsesFallback.value ? 'Preview生成于' : '距今',
      value: formatRelativeAge(ageSource.value, now.value),
      testid: 'research-data-age',
    },
    { label: '对应交易日', value: props.tradeDate || '—', testid: 'research-trade-date' },
    { label: '数据源', value: previewProviderLabel(props.provider), testid: 'research-provider' },
    { label: '上次正式结果', value: props.officialTradeDate || '—', testid: 'research-official-trade-date' },
  ];
});
</script>

<template>
  <section
    class="rounded-md border px-3 py-2 text-sm"
    data-testid="research-data-status"
    :data-mode="mode"
  >
    <div class="mb-2 flex flex-wrap items-center gap-2">
      <Badge
        :variant="mode === 'preview' ? 'warning' : 'outline'"
        data-testid="research-data-mode-badge"
      >
        {{ previewUnavailable ? '盘中预演不可用' : mode === 'preview' ? '盘中预演' : '正式收盘' }}
      </Badge>
      <span
        v-if="previewUsable"
        class="text-xs text-amber-700 dark:text-amber-300"
      >用当前盘中行情模拟“如果现在收盘”</span>
    </div>
    <dl class="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 xl:grid-cols-4">
      <div
        v-for="field in fields"
        :key="field.label"
        class="flex min-w-0 items-baseline justify-between gap-3 sm:justify-start"
      >
        <dt class="shrink-0 text-muted-foreground">
          {{ field.label }}
        </dt>
        <TooltipProvider :delay-duration="150">
          <Tooltip :disabled="!field.title">
            <TooltipTrigger as-child>
              <dd
                class="min-w-0 truncate font-medium tabular-nums"
                :data-testid="field.testid"
                :aria-label="field.title"
              >
                {{ field.value }}
              </dd>
            </TooltipTrigger>
            <TooltipContent v-if="field.title">
              {{ field.title }}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </dl>
  </section>
</template>
