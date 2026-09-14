<script setup lang="ts">
import type { MacroInstrument, MacroRatio } from '@/api/macro';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { formatDateOnly } from '@/utils/format';
import { numberLabel, returnClass, returnLabel, seriesLabel, trendLabel, regimeLabel } from './display';
defineProps<{ rows: (MacroInstrument | MacroRatio)[]; ratios?: boolean }>();
const categories: Record<string, string> = { EQUITY: '权益', RATES: '利率', DOLLAR: '美元', COMMODITY: '商品', CREDIT: '信用', RISK: '风险偏好', DEFENSIVE: '防御', VOLATILITY: '波动率' };
</script>
<template>
  <Card
    class="min-w-0"
    :data-testid="ratios ? 'macro-ratio-table' : 'macro-instrument-table'"
  >
    <CardHeader><CardTitle>{{ ratios ? '宏观 Ratio' : '宏观资产' }}</CardTitle></CardHeader>
    <CardContent>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{{ ratios ? '指标' : '资产' }}</TableHead><TableHead v-if="!ratios">
              类别
            </TableHead><TableHead class="text-right">
              {{ ratios ? '当前值' : '最新价' }}
            </TableHead><TableHead
              v-for="period in ['1D', '5D', '20D']"
              :key="period"
              class="text-right"
            >
              {{ period }}
            </TableHead><TableHead>趋势</TableHead><TableHead v-if="ratios">
              信号
            </TableHead><TableHead>数据日期</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in rows"
            :key="'code' in row ? row.code : row.key"
          >
            <TableCell>
              <p class="font-medium">
                {{ seriesLabel('code' in row ? row.code : row.key) }}
              </p><p class="text-xs text-muted-foreground">
                {{ row.name }}
              </p><Badge
                v-if="'partial' in row && row.partial"
                variant="outline"
              >
                数据不完整
              </Badge>
            </TableCell>
            <TableCell v-if="'category' in row">
              <Badge variant="secondary">
                {{ categories[row.category] ?? row.category }}
              </Badge>
            </TableCell>
            <TableCell class="text-right tabular-nums">
              {{ 'close' in row ? numberLabel(row.close) : numberLabel(row.value, 3) }}
            </TableCell>
            <TableCell
              v-for="key in (['ret1D', 'ret5D', 'ret20D'] as const)"
              :key="key"
              class="text-right tabular-nums"
              :class="returnClass(row[key])"
            >
              {{ returnLabel(row[key]) }}
            </TableCell>
            <TableCell>{{ trendLabel(row.trend) }}</TableCell><TableCell v-if="'signal' in row">
              {{ regimeLabel(row.signal) }}
            </TableCell><TableCell class="tabular-nums">
              {{ formatDateOnly(row.tradeDate) }}
            </TableCell>
          </TableRow>
          <TableRow v-if="!rows.length">
            <TableCell
              :colspan="8"
              class="py-10 text-center text-muted-foreground"
            >
              暂无宏观数据
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardContent>
  </Card>
</template>
