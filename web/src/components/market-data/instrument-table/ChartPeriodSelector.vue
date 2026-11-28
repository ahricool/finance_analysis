<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { periods, type ChartPeriod } from './state';
const period = defineModel<ChartPeriod>({ required: true });
</script>
<template>
  <div
    class="flex flex-wrap items-center gap-1 rounded-lg border bg-background p-1"
    role="group"
    aria-label="K 线周期"
  >
    <span class="mr-1 text-xs text-muted-foreground">K 线周期</span>
    <Button
      v-for="[value, label] in periods"
      :key="value"
      size="sm"
      :variant="period === value ? 'secondary' : 'ghost'"
      :aria-pressed="period === value"
      @click="period = value"
    >
      {{ label }}
    </Button>
  </div>
</template>
