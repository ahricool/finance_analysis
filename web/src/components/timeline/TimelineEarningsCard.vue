<script setup lang="ts">
import { computed } from 'vue';
import type { TimelineItem } from '@/api/timeline';
import TimelineCardShell from './TimelineCardShell.vue';
import { clockTime, dayHeading, dayKey, distanceLabel, formatEps, formatSurprise, hasValue, sessionLabel } from './timelineFormat';

const props = defineProps<{ item: TimelineItem }>();
defineEmits<{ open: [] }>();

const payload = computed(() => props.item.detailPayload);
const session = computed(() => sessionLabel(payload.value.marketSession));
const when = computed(() => {
  const day = dayHeading(dayKey(props.item.eventTime));
  if (session.value) return `${day} · ${session.value}`;
  return payload.value.allDay ? `${day} · 时间待定` : `${day} · ${clockTime(props.item.eventTime)}`;
});
const estimate = computed(() => formatEps(payload.value.epsEstimate, payload.value.currency));
const reported = computed(() => formatEps(payload.value.reportedEps, payload.value.currency));
const surprise = computed(() => formatSurprise(payload.value.epsSurprisePct));
</script>

<template>
  <TimelineCardShell
    :item="item"
    @open="$emit('open')"
  >
    <template #meta>
      <span>{{ distanceLabel(item) }}</span>
    </template>
    <p class="break-words text-[15px] font-semibold leading-snug tracking-tight">
      <span class="tabular-nums">{{ item.symbol || item.title }}</span>
      <span
        v-if="hasValue(payload.counterName)"
        class="mt-0.5 block text-sm font-medium text-muted-foreground"
      >{{ payload.counterName }}</span>
    </p>
    <p
      v-if="payload.reportingPeriod || item.title"
      class="mt-1.5 break-words text-sm text-muted-foreground"
    >
      {{ payload.reportingPeriod || item.title }}
    </p>
    <p class="mt-1 break-words text-[11px] leading-4 text-muted-foreground">
      {{ when }}
    </p>
    <p
      v-if="estimate || reported"
      class="mt-1.5 flex flex-wrap gap-x-2 gap-y-1 text-sm tabular-nums"
    >
      <span v-if="estimate">EPS 预期 {{ estimate }}</span>
      <span v-if="reported">实际 {{ reported }}</span>
      <span
        v-if="surprise"
        :class="(payload.epsSurprisePct as number) >= 0 ? 'text-market-up' : 'text-market-down'"
      >Surprise {{ surprise }}</span>
    </p>
  </TimelineCardShell>
</template>
