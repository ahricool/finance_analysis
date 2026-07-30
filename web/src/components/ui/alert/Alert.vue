<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import type { AlertVariants } from '.';
import { cn } from '@/utils/cn';
import { alertVariants } from '.';
const props = defineProps<{ class?: HTMLAttributes['class']; variant?: AlertVariants['variant'] }>();
</script>
<template>
  <div
    role="alert"
    data-slot="alert"
    :class="cn(alertVariants({ variant }), props.class)"
  >
    <slot />
  </div>
</template>
