<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = defineProps<{ class?: HTMLAttributes['class']; containerClass?: HTMLAttributes['class'] }>();
</script>
<template>
  <div
    data-slot="table-container"
    :class="cn('relative w-full overflow-x-auto', props.containerClass)"
  >
    <table
      data-slot="table"
      :class="cn('w-full min-w-max caption-bottom text-sm', props.class)"
    >
      <slot />
    </table>
  </div>
</template>
