<script setup lang="ts">
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import { metricHint } from '@/utils/metricHints';

withDefaults(defineProps<{
  /** Glossary key from metricLabels, or Chinese fallback text. */
  label: string;
  en?: string;
  description?: string;
  scope?: string;
  wrap?: boolean;
  compact?: boolean;
}>(), {
  en: undefined,
  description: undefined,
  scope: undefined,
  wrap: false,
  compact: false,
});
</script>

<template>
  <BilingualLabel
    :label="en ? undefined : label"
    :zh="en ? label : undefined"
    :en="en"
    :description="description ?? metricHint(scope, label)"
    :wrap="wrap"
    :compact="compact"
  />
</template>
