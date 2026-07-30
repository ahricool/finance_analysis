<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = withDefaults(defineProps<{ class?: HTMLAttributes['class']; variant?: 'default' | 'icon' }>(), { variant: 'default', class: undefined });
</script>
<template>
  <div
    data-slot="empty-media"
    :class="cn('mb-2 flex shrink-0 items-center justify-center [&_svg]:shrink-0', variant === 'icon' && 'size-10 rounded-lg bg-muted text-foreground [&_svg]:size-6', props.class)"
  >
    <slot />
  </div>
</template>
