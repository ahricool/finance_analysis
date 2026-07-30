<script setup lang="ts">
import type { HTMLAttributes } from 'vue'; import { cn } from '@/utils/cn'; const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <td
    data-slot="table-cell"
    :class="cn('whitespace-nowrap p-2 align-middle', props.class)"
  >
    <slot />
  </td>
</template>
