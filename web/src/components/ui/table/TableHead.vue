<script setup lang="ts">
import type { HTMLAttributes } from 'vue'; import { cn } from '@/utils/cn'; const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <th
    data-slot="table-head"
    :class="cn('h-10 whitespace-nowrap px-2 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0', props.class)"
  >
    <slot />
  </th>
</template>
