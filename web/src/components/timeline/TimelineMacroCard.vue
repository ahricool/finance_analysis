<script setup lang="ts">
import { computed } from 'vue';
import type { TimelineItem } from '@/api/timeline';
import TimelineCardShell from './TimelineCardShell.vue';
import { clockTime, dayHeading, dayKey, distanceLabel, hasValue } from './timelineFormat';

const props = defineProps<{ item: TimelineItem }>();
defineEmits<{ open: [] }>();

const when = computed(() => {
  const day = dayHeading(dayKey(props.item.eventTime));
  return props.item.detailPayload.allDay ? `${day} · 时间待定` : `${day} · ${clockTime(props.item.eventTime)}`;
});
</script>

<template>
  <TimelineCardShell
    :item="item"
    @open="$emit('open')"
  >
    <template #meta>
      <span>· {{ distanceLabel(item) }}</span>
    </template>
    <p class="break-words text-base font-semibold leading-snug">
      {{ item.title }}
    </p>
    <p class="mt-2 text-xs text-muted-foreground">
      {{ when }}
    </p>
    <p
      v-if="hasValue(item.summary)"
      class="mt-2 line-clamp-2 text-sm leading-relaxed text-muted-foreground"
    >
      {{ item.summary }}
    </p>
  </TimelineCardShell>
</template>
