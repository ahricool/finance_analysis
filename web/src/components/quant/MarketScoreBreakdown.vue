<script setup lang="ts">
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useGroupedTableSort, sortField } from '@/composables/useTableSort';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricHint } from '@/utils/metricHints';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import type { MarketScoreBreakdown, MarketScoreComponent } from '@/types/quant';
import { formatPercent, formatScore } from '@/utils/quant';

const props = defineProps<{ breakdown: MarketScoreBreakdown }>();

function formatRaw(component: MarketScoreComponent): string {
  return component.rawFormat === 'percent'
    ? formatPercent(component.rawValue)
    : formatScore(component.rawValue);
}

const groupTable = useGroupedTableSort((key: string) => props.breakdown.groups.find(group => group.key === key)?.components ?? [], sortField);

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
              <SortableTableHeader
                label="指标"
                scope="quant"
                v-bind="groupTable(group.key).header('label')"
              />
              <SortableTableHeader
                label="原始值"
                scope="quant"
                v-bind="groupTable(group.key).header('rawValue')"
              />
              <SortableTableHeader
                label="标准化得分"
                scope="quant"
                v-bind="groupTable(group.key).header('score')"
              />
              <SortableTableHeader
                label="权重"
                scope="quant"
                v-bind="groupTable(group.key).header('weight')"
              />
              <SortableTableHeader
                label="贡献"
                scope="quant"
                v-bind="groupTable(group.key).header('contribution')"
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="component in groupTable(group.key).sorted"
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
