<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <ol
    data-slot="breadcrumb-list"
    :class="cn('flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground sm:gap-2.5', props.class)"
  >
    <slot />
  </ol>
</template>
