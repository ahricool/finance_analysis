<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    class?: string;
    titleClassName?: string;
    descriptionClassName?: string;
    compact?: boolean;
    loading?: boolean;
    titleAs?: 'p' | 'h2' | 'h3' | 'h4' | 'span';
  }>(),
  {
    compact: false,
    loading: false,
    titleAs: 'p',
    class: '',
    titleClassName: '',
    descriptionClassName: '',
  },
);

const titleTag = computed(() => props.titleAs);
</script>

<template>
  <div
    :class="
      cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 py-6' : 'gap-3 py-10',
        props.class,
      )
    "
  >
    <div v-if="loading" class="home-spinner h-6 w-6 animate-spin border-2" aria-hidden="true" />
    <div
      v-else-if="$slots.icon"
      class="home-state-icon-muted flex h-11 w-11 items-center justify-center rounded-full bg-subtle"
    >
      <slot name="icon" />
    </div>

    <div class="space-y-1">
      <component
        :is="titleTag"
        :class="
          cn(
            'text-secondary-text',
            compact ? 'text-xs' : 'text-sm',
            titleClassName,
          )
        "
      >
        {{ title }}
      </component>
      <p
        v-if="description"
        :class="
          cn(
            'mx-auto max-w-xs text-secondary-text',
            compact ? 'text-label' : 'text-xs',
            descriptionClassName,
          )
        "
      >
        {{ description }}
      </p>
    </div>
    <div v-if="$slots.action" class="flex items-center justify-center">
      <slot name="action" />
    </div>
  </div>
</template>
