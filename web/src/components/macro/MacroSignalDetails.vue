<script setup lang="ts">
import type { MacroDashboard } from '@/api/macro';
import { Button } from '@/components/ui/button';
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { seriesLabel, trendLabel } from './display';
defineProps<{ dashboard: MacroDashboard }>();
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
          <TableHeader><TableRow><TableHead>信号</TableHead><TableHead>趋势</TableHead><TableHead>Risk On 条件</TableHead><TableHead>贡献 / 权重</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow
              v-for="signal in dashboard.signals"
              :key="signal.key"
            >
              <TableCell>{{ seriesLabel(signal.key) }}</TableCell><TableCell>{{ trendLabel(signal.trend) }}</TableCell><TableCell>{{ trendLabel(signal.riskOnTrend) }}</TableCell>
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
