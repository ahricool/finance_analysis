<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { optionHelp } from './help';
defineProps<{ label: string; compact?: boolean; en?: string }>();
</script>
<template>
  <IndicatorHelpLabel
    :label="label"
    :en="en"
    :compact="compact"
    :description="optionHelp[label] ?? label"
  />
</template>
