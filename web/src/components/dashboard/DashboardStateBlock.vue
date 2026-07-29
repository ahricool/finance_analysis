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
    description: '',
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
    <div
      v-if="loading"
      class="size-6 animate-spin rounded-full border-2 border-primary/25 border-t-primary"
      aria-hidden="true"
    />
    <div
      v-else-if="$slots.icon"
      class="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground"
    >
      <slot name="icon" />
    </div>

    <div class="space-y-1">
      <component
        :is="titleTag"
        :class="cn('text-muted-foreground', compact ? 'text-xs' : 'text-sm', titleClassName)"
      >
        {{ title }}
      </component>
      <p
        v-if="description"
        :class="
          cn(
            'mx-auto max-w-xs text-muted-foreground',
            'text-xs',
            descriptionClassName,
          )
        "
      >
        {{ description }}
      </p>
    </div>
    <div
      v-if="$slots.action"
      class="flex items-center justify-center"
    >
      <slot name="action" />
    </div>
  </div>
</template>
