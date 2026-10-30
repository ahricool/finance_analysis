<script setup lang="ts">
import { metricHint } from '@/utils/metricHints';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useTableSort, sortField } from '@/composables/useTableSort';
import StockLink from '@/components/stocks/StockLink.vue';
import type { MacroDashboard } from '@/api/macro';
import { Button } from '@/components/ui/button';
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { seriesLabel, trendLabel } from './display';
const props = defineProps<{ dashboard: MacroDashboard }>();

const table = useTableSort(() => props.dashboard.signals, (row, key) => {
  if (key === 'key') return props.dashboard.instruments.find(item => item.code === row.key)?.name ?? seriesLabel(row.key);
  if (key === 'trend' || key === 'riskOnTrend') return ({ UP: 0, NEUTRAL: 1, DOWN: 2 } as Record<string, number>)[String(row[key])];
  return sortField(row, key);
});
</script>
<template>
  <Sheet>
    <SheetTrigger as-child>
      <Button
        variant="link"
        size="sm"
        class="h-auto p-0"
        data-testid="macro-signal-details"
      >
        查看构成
      </Button>
    </SheetTrigger>
    <SheetContent class="overflow-y-auto sm:max-w-xl">
      <SheetHeader><SheetTitle>Risk Score 构成</SheetTitle><SheetDescription>后端返回的信号与贡献；N/A 不计入可用权重。</SheetDescription></SheetHeader>
      <div class="px-4 pb-6">
        <Table>
          <TableHeader>
            <TableRow>
              <SortableTableHeader
                label="信号"
                scope="macroSignal"
                v-bind="table.header('key')"
              /><SortableTableHeader
                label="趋势"
                scope="macroSignal"
                v-bind="table.header('trend')"
              /><SortableTableHeader
                label="Risk On 条件"
                scope="macroSignal"
                v-bind="table.header('riskOnTrend')"
              /><SortableTableHeader
                label="贡献 / 权重"
                :description="[metricHint('macroSignal', '贡献 / 权重'), '按贡献值排序'].filter(Boolean).join('；')"
                scope="macroSignal"
                v-bind="table.header('contribution')"
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="signal in table.sorted"
              :key="signal.key"
            >
              <TableCell>
                <StockLink
                  v-if="signal.key.endsWith('.US')"
                  :code="signal.key"
                  :name="dashboard.instruments.find(item => item.code === signal.key)?.name"
                  market="US"
                /><span v-else>{{ seriesLabel(signal.key) }}</span>
              </TableCell><TableCell>{{ trendLabel(signal.trend) }}</TableCell><TableCell>{{ trendLabel(signal.riskOnTrend) }}</TableCell>
              <TableCell>
                <span class="tabular-nums">{{ signal.contribution === null ? 'N/A' : `+${signal.contribution}` }} / {{ signal.weight }}</span><p
                  v-if="signal.contribution === null"
                  class="text-xs text-muted-foreground"
                >
                  数据不足 / 过期（stale）
                </p>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </SheetContent>
  </Sheet>
</template>
