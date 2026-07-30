<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <div
    data-slot="alert-description"
    :class="cn('text-sm text-muted-foreground group-data-[variant=destructive]/alert:text-destructive/90', props.class)"
  >
    <slot />
  </div>
</template>
