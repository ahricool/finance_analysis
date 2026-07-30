<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <span
    data-slot="breadcrumb-page"
    role="link"
    aria-disabled="true"
    aria-current="page"
    :class="cn('font-normal text-foreground', props.class)"
  ><slot /></span>
</template>
