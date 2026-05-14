<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    title?: string;
    subtitle?: string;
    variant?: 'default' | 'bordered' | 'gradient';
    hoverable?: boolean;
    padding?: 'none' | 'sm' | 'md' | 'lg';
    class?: string;
    rootStyle?: Record<string, string>;
  }>(),
  {
    variant: 'default',
    hoverable: false,
    padding: 'md',
    class: '',
  },
);

const paddingStyles: Record<'none' | 'sm' | 'md' | 'lg', string> = {
  none: '',
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
};

const headerBlock = computed(
  () =>
    props.title || props.subtitle
      ? { subtitle: props.subtitle, title: props.title }
      : null,
);

const innerPadding = computed(() => paddingStyles[props.padding]);

const gradientClass = computed(() => cn('gradient-border-card', props.class));

const flatClass = computed(() =>
  cn(
    'rounded-2xl',
    props.variant === 'default' || props.variant === 'bordered' ? 'terminal-card' : '',
    props.hoverable ? 'terminal-card-hover cursor-pointer' : '',
    innerPadding.value,
    props.class,
  ),
);
</script>

<template>
  <div v-if="variant === 'gradient'" :class="gradientClass" :style="rootStyle">
    <div :class="cn('gradient-border-card-inner', innerPadding)">
      <div v-if="headerBlock" class="mb-3">
        <span v-if="headerBlock.subtitle" class="label-uppercase">{{ headerBlock.subtitle }}</span>
        <h3 v-if="headerBlock.title" class="mt-1 text-lg font-semibold text-foreground">
          {{ headerBlock.title }}
        </h3>
      </div>
      <slot />
    </div>
  </div>
  <div v-else :class="flatClass" :style="rootStyle">
    <div v-if="headerBlock" class="mb-3">
      <span v-if="headerBlock.subtitle" class="label-uppercase">{{ headerBlock.subtitle }}</span>
      <h3 v-if="headerBlock.title" class="mt-1 text-lg font-semibold text-foreground">
        {{ headerBlock.title }}
      </h3>
    </div>
    <slot />
  </div>
</template>
