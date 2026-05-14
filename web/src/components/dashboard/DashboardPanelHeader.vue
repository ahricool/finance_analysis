<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, useSlots } from 'vue';

const props = withDefaults(
  defineProps<{
    class?: string;
    headingClassName?: string;
    titleClassName?: string;
    accentEyebrow?: boolean;
  }>(),
  {
    class: '',
    headingClassName: '',
    titleClassName: '',
    accentEyebrow: false,
  },
);

const slots = useSlots();

const show = computed(() => Boolean(slots.eyebrow || slots.title || slots.actions));
</script>

<template>
  <div v-if="show" :class="cn('mb-4 flex items-center justify-between gap-3', props.class)">
    <div v-if="$slots.eyebrow || $slots.title" :class="cn('flex items-baseline gap-2', headingClassName)">
      <span v-if="$slots.leading" class="shrink-0">
        <slot name="leading" />
      </span>
      <span v-if="$slots.eyebrow" :class="cn('label-uppercase', accentEyebrow && 'home-title-accent')">
        <slot name="eyebrow" />
      </span>
      <h3 v-if="$slots.title" :class="cn('text-base font-semibold text-foreground', titleClassName)">
        <slot name="title" />
      </h3>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
