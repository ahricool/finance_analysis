<script setup lang="ts">
import BilingualLabel from '@/components/app/BilingualLabel.vue';

withDefaults(defineProps<{
  /** Glossary key from metricLabels, or Chinese fallback text. */
  label: string;
  en?: string;
  description: string;
  wrap?: boolean;
  compact?: boolean;
}>(), {
  wrap: false,
  compact: false,
});
</script>

<template>
  <BilingualLabel
    :label="en ? undefined : label"
    :zh="en ? label : undefined"
    :en="en"
    :description="description"
    :wrap="wrap"
    :compact="compact"
  />
</template>
