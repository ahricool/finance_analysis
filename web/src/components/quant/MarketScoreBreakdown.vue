<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricHint } from '@/utils/metricHints';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { MarketScoreBreakdown, MarketScoreComponent } from '@/types/quant';
import { formatPercent, formatScore } from '@/utils/quant';

defineProps<{ breakdown: MarketScoreBreakdown }>();

function formatRaw(component: MarketScoreComponent): string {
  return component.rawFormat === 'percent'
    ? formatPercent(component.rawValue)
    : formatScore(component.rawValue);
}
</script>

<template>
  <div
    class="grid gap-3 xl:grid-cols-2"
    data-testid="market-score-breakdown"
  >
    <section
      v-for="group in breakdown.groups"
      :key="group.key"
      class="min-w-0 rounded-lg border border-border"
    >
      <div class="flex flex-wrap items-start justify-between gap-2 border-b border-border p-4">
        <div>
          <h4 class="font-medium">
            {{ group.label }}
          </h4>
          <p class="text-xs text-muted-foreground">
            <IndicatorHelpLabel
              scope="quant"
              label="分组得分"
              compact
            /> {{ formatScore(group.score) }}
          </p>
        </div>
        <div class="text-right text-xs text-muted-foreground">
          <p>权重 {{ formatPercent(group.weight) }}</p>
          <p>贡献 {{ formatScore(group.contribution, 3) }}</p>
        </div>
      </div>
      <div class="overflow-x-auto">
        <Table class="min-w-[620px]">
          <TableHeader>
            <TableRow>
              <TableHead>
                <IndicatorHelpLabel
                  scope="quant"
                  label="指标"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="quant"
                  label="原始值"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="quant"
                  label="标准化得分"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="quant"
                  label="权重"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="quant"
                  label="贡献"
                  compact
                />
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="component in group.components"
              :key="component.key"
            >
              <TableCell class="font-medium">
                <IndicatorHelpLabel
                  :label="component.label"
                  :description="metricHint('quant', component.key)"
                  compact
                />
              </TableCell>
              <TableCell>{{ formatRaw(component) }}</TableCell>
              <TableCell>{{ formatScore(component.score) }}</TableCell>
              <TableCell>{{ formatPercent(component.weight) }}</TableCell>
              <TableCell>{{ formatScore(component.contribution, 3) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </section>
  </div>
</template>
