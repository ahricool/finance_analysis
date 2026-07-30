<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    strategy?: ReportStrategyType;
    language?: ReportLanguage;
  }>(),
  {
    strategy: undefined,
    language: 'zh',
  },
);

const text = computed(() => getReportText(normalizeReportLanguage(props.language)));

const items = computed(() => {
  const s = props.strategy;
  const t = text.value;
  if (!s) return [];
  return [
    { label: t.idealBuy, value: s.idealBuy, toneClass: 'text-market-up', barClass: 'bg-market-up' },
    {
      label: t.secondaryBuy,
      value: s.secondaryBuy,
      toneClass: 'text-warning',
      barClass: 'bg-warning',
    },
    {
      label: t.stopLoss,
      value: s.stopLoss,
      toneClass: 'text-destructive',
      barClass: 'bg-destructive',
    },
    { label: t.takeProfit, value: s.takeProfit, toneClass: 'text-success', barClass: 'bg-success' },
  ];
});
</script>

<template>
  <Card v-if="strategy">
    <CardHeader>
      <CardTitle>{{ text.sniperLevels }}</CardTitle>
      <CardDescription>{{ text.strategyPoints }}</CardDescription>
    </CardHeader>
    <CardContent class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div
        v-for="item in items"
        :key="item.label"
        class="relative rounded-xl border bg-muted/40 p-3"
      >
        <div class="flex flex-col">
          <span class="mb-0.5 text-xs">{{ item.label }}</span>
          <span
            class="font-mono text-lg font-bold"
            :class="item.value ? item.toneClass : 'text-muted-foreground'"
          >
            {{ item.value || '—' }}
          </span>
        </div>
        <div :class="['absolute inset-x-0 bottom-0 h-0.5 opacity-70', item.barClass]" />
      </div>
    </CardContent>
  </Card>
</template>
