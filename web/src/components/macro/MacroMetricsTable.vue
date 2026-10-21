<script setup lang="ts">
import StockIdentity from '@/components/stocks/StockIdentity.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import type { MacroInstrument, MacroRatio } from '@/api/macro';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { formatDateOnly } from '@/utils/format';
import { numberLabel, returnClass, returnLabel, seriesLabel, trendLabel, regimeLabel } from './display';
const emit = defineEmits<{ select: [asset: MacroInstrument] }>();
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
              <IndicatorHelpLabel
                scope="macro"
                label="类别"
                compact
              />
            </TableHead><TableHead class="text-right">
              <IndicatorHelpLabel
                scope="macro"
                :label="ratios ? '当前值' : '最新价'"
                compact
              />
            </TableHead><TableHead
              v-for="period in ['1D', '5D', '20D']"
              :key="period"
              class="text-right"
            >
              <IndicatorHelpLabel
                scope="macro"
                :label="period"
                compact
              />
            </TableHead><TableHead>
              <IndicatorHelpLabel
                scope="macro"
                label="趋势"
                compact
              />
            </TableHead><TableHead v-if="ratios">
              <IndicatorHelpLabel
                scope="macro"
                label="信号"
                compact
              />
            </TableHead><TableHead>
              <IndicatorHelpLabel
                scope="macro"
                label="数据日期"
                compact
              />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in rows"
            :key="'code' in row ? row.code : row.key"
            :class="{ 'cursor-pointer': 'code' in row }"
            @click="'code' in row && emit('select', row)"
          >
            <TableCell>
              <button
                v-if="'code' in row"
                type="button"
                class="rounded-sm font-medium text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :aria-label="`查看 ${row.code} ${row.name} 详情`"
                @click.stop="emit('select', row)"
              >
                <StockIdentity
                  :code="row.code"
                  :name="row.name"
                />
              </button>
              <p
                v-else
                class="font-medium"
              >
                {{ seriesLabel(row.key) }}
              </p><p
                v-if="!('code' in row)"
                class="text-xs text-muted-foreground"
              >
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
