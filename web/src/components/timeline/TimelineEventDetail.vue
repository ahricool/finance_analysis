<script setup lang="ts">
import { computed } from 'vue';
import type { TimelineItem } from '@/api/timeline';
import { clockTime, dayHeading, dayKey, formatEps, formatSurprise, hasValue, sessionLabel } from './timelineFormat';

const props = defineProps<{ item: TimelineItem }>();

const payload = computed(() => props.item.detailPayload);
const when = computed(() => {
  const day = dayHeading(dayKey(props.item.eventTime));
  const session = sessionLabel(payload.value.marketSession);
  if (session) return `${day} · ${session}`;
  return payload.value.allDay ? `${day} · 时间待定` : `${day} · ${clockTime(props.item.eventTime)}`;
});
const facts = computed(() =>
  [
    ['标的', props.item.symbol],
    ['名称', payload.value.counterName],
    ['报告期', payload.value.reportingPeriod],
    ['EPS 预期', formatEps(payload.value.epsEstimate)],
    ['实际 EPS', formatEps(payload.value.reportedEps)],
    ['EPS Surprise', formatSurprise(payload.value.epsSurprisePct)],
    ['计价货币', payload.value.currency],
  ].filter(([, value]) => hasValue(value)) as [string, string][],
);
const providers = computed(() => payload.value.sourceProviders ?? []);
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-muted-foreground">
      {{ when }}
    </p>
    <dl
      v-if="facts.length"
      class="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3"
    >
      <div
        v-for="[label, value] in facts"
        :key="label"
      >
        <dt class="text-xs text-muted-foreground">
          {{ label }}
        </dt>
        <dd class="mt-0.5 text-sm font-medium tabular-nums">
          {{ value }}
        </dd>
      </div>
    </dl>
    <div v-if="hasValue(payload.importanceReason)">
      <p class="text-xs text-muted-foreground">
        重要性依据
      </p>
      <p class="mt-1 whitespace-pre-line text-sm leading-relaxed">
        {{ payload.importanceReason }}
      </p>
    </div>
    <p
      v-if="hasValue(payload.content)"
      class="whitespace-pre-line text-sm leading-relaxed"
    >
      {{ payload.content }}
    </p>
    <p
      v-if="providers.length"
      class="border-t border-border pt-3 text-xs text-muted-foreground"
    >
      数据来源：{{ providers.join(' · ') }}
    </p>
  </div>
</template>
