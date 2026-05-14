<script setup lang="ts">
import Card from '@/components/common/Card.vue';
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    strategy?: ReportStrategyType;
    language?: ReportLanguage;
  }>(),
  {
    language: 'zh',
  },
);

const text = computed(() => getReportText(normalizeReportLanguage(props.language)));

const items = computed(() => {
  const s = props.strategy;
  const t = text.value;
  if (!s) return [];
  return [
    { label: t.idealBuy, value: s.idealBuy, toneVar: '--home-strategy-buy' },
    { label: t.secondaryBuy, value: s.secondaryBuy, toneVar: '--home-strategy-secondary' },
    { label: t.stopLoss, value: s.stopLoss, toneVar: '--home-strategy-stop' },
    { label: t.takeProfit, value: s.takeProfit, toneVar: '--home-strategy-take' },
  ];
});
</script>

<template>
  <Card v-if="strategy" variant="bordered" padding="md" class="home-panel-card">
    <DashboardPanelHeader class="mb-3">
      <template #eyebrow>{{ text.strategyPoints }}</template>
      <template #title>{{ text.sniperLevels }}</template>
    </DashboardPanelHeader>
    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div
        v-for="item in items"
        :key="item.label"
        class="home-subpanel home-strategy-card relative p-3"
        :style="{ '--home-strategy-tone': `var(${item.toneVar})` }"
      >
        <div class="flex flex-col">
          <span class="home-strategy-label mb-0.5 text-xs">{{ item.label }}</span>
          <span
            class="home-strategy-value font-mono text-lg font-bold"
            :style="!item.value ? { color: 'var(--text-muted-text)' } : undefined"
          >
            {{ item.value || '—' }}
          </span>
        </div>
        <div
          class="absolute bottom-0 left-0 right-0 h-0.5"
          :style="{ background: `linear-gradient(90deg, transparent, var(${item.toneVar}), transparent)` }"
        />
      </div>
    </div>
  </Card>
</template>
