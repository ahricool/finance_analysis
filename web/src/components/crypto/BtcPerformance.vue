<script setup lang="ts">
import { metricHint } from '@/utils/metricHints';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useTableSort, sortField, sortNumber, sortTime } from '@/composables/useTableSort';
import { computed } from 'vue';
import type { CryptoPerformance } from '@/types/crypto';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
const props = defineProps<{ performance: CryptoPerformance; price: string | null }>();
const percent = (value: string | number | null | undefined) => value == null ? '—' : Number.isFinite(Number(value) * 100) ? `${(Number(value) * 100).toFixed(2)}%` : `${value} × 100%`;
const number = (value: string | null) => value == null ? '—' : Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
const floating = computed(() => props.price && Number(props.performance.currentPosition.averageEntryPrice) > 0
  ? Number(props.price) / Number(props.performance.currentPosition.averageEntryPrice) - 1 : null);
const metrics = computed(() => [
  ['当前仓位', percent(props.performance.currentPosition.positionPct)],
  ['平均成本', number(props.performance.currentPosition.averageEntryPrice)],
  ['当前 BTC 浮盈率', percent(floating.value)],
  ['持仓浮动贡献', percent(floating.value == null ? null : Number(props.performance.currentPosition.positionPct) * floating.value)],
  ['年化收益 CAGR', percent(props.performance.annualizedReturn)], ['运行天数', Number(props.performance.runningDays).toFixed(2)],
  ['累计收益', percent(props.performance.totalReturn)], ['最大回撤', percent(props.performance.maxDrawdown)],
  ['胜率', percent(props.performance.winRate)], ['完整交易次数', props.performance.closedTrades],
  ['执行次数', props.performance.executionCount], ['平均交易收益', percent(props.performance.averageTradeReturn)],
]);
const curve = computed(() => {
  const values = props.performance.equityCurve.map(point => Number(point.equity));
  const low = values.reduce((a, b) => Math.min(a, b), 1), high = values.reduce((a, b) => Math.max(a, b), 1);
  return values.map((value, index) => `${10 + index / Math.max(values.length - 1, 1) * 980},${110 - (value - low) / (high - low || 1) * 90}`).join(' ');
});

const executionTable = useTableSort(() => props.performance.recentExecutions, (row, key) => key === 'evaluatedAt' ? sortTime(row.evaluatedAt) : key === 'action' ? row.action : sortNumber(sortField(row, key)));
const tradeTable = useTableSort(() => props.performance.recentTrades, (row, key) => key === 'entryTime' ? sortTime(row.entryTime) : sortNumber(sortField(row, key)));

</script>
<template>
  <Card data-testid="btc-performance">
    <CardHeader>
      <CardTitle>
        <IndicatorHelpLabel
          scope="crypto"
          label="performance"
        />
      </CardTitle>
      <CardDescription>{{ performance.displayName }} · 有效起点 {{ performance.performanceStartAt ?? '等待完整仓位快照' }} · 截至 {{ performance.performanceEndAt ?? '—' }} · 15m 收盘净值，初始为 1 · 无手续费与滑点</CardDescription>
    </CardHeader>
    <CardContent class="space-y-5">
      <div class="grid grid-cols-5 gap-4">
        <div
          v-for="[label, value] in metrics"
          :key="label"
          class="space-y-1"
        >
          <p
            v-if="performance.equityPointsTotal > performance.equityCurve.length"
            class="text-xs text-muted-foreground"
          >
            曲线显示抽样点，收益与回撤仍按全部 {{ performance.equityPointsTotal }} 条快照计算。
          </p>
          <p class="text-xs text-muted-foreground">
            <IndicatorHelpLabel
              scope="crypto"
              :label="String(label)"
              compact
            />
          </p><strong class="tabular-nums">{{ value }}</strong>
        </div>
      </div>
      <svg
        v-if="performance.equityCurve.length > 1"
        viewBox="0 0 1000 130"
        class="h-32 w-full"
        role="img"
        aria-label="策略净值曲线，基于每个15分钟快照"
      >
        <polyline
          :points="curve"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          class="text-primary"
        />
      </svg>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        净值曲线等待更多完整的 15m 快照。
      </p>
      <p class="text-xs text-muted-foreground">
        浮盈按浏览器 Binance 价格计算；持仓浮动贡献 = 仓位 × 相对平均成本收益。胜率仅含完整持仓周期，未完成周期不计入。
      </p>
      <div class="grid grid-cols-2 gap-6">
        <section>
          <h4 class="mb-2 font-medium">
            <IndicatorHelpLabel
              scope="crypto"
              label="recentExecutions"
            />
          </h4>
          <p
            v-if="!performance.recentExecutions.length"
            class="text-sm text-muted-foreground"
          >
            暂无完整仓位变化
          </p>
          <Table v-else>
            <TableHeader>
              <TableRow>
                <SortableTableHeader
                  label="时间 UTC"
                  scope="crypto"
                  v-bind="executionTable.header('evaluatedAt')"
                /><SortableTableHeader
                  label="操作"
                  scope="crypto"
                  v-bind="executionTable.header('action')"
                /><SortableTableHeader
                  label="仓位"
                  :description="[metricHint('crypto', '仓位'), '按调整后仓位排序'].filter(Boolean).join('；')"
                  scope="crypto"
                  v-bind="executionTable.header('positionAfter')"
                /><SortableTableHeader
                  label="价格"
                  scope="crypto"
                  v-bind="executionTable.header('price')"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="item in executionTable.sorted.slice(0, 10)"
                :key="item.evaluatedAt"
              >
                <TableCell>{{ item.evaluatedAt.replace('T', ' ').slice(0, 16) }}</TableCell><TableCell>
                  <BilingualEnum
                    :value="item.action"
                    size="badge"
                  />
                </TableCell><TableCell>{{ percent(item.positionBefore) }} → {{ percent(item.positionAfter) }}</TableCell><TableCell>{{ number(item.price) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>
        <section>
          <h4 class="mb-2 font-medium">
            <IndicatorHelpLabel
              scope="crypto"
              label="recentTrades"
            />
          </h4>
          <p
            v-if="!performance.recentTrades.length"
            class="text-sm text-muted-foreground"
          >
            暂无完整持仓周期
          </p>
          <Table v-else>
            <TableHeader>
              <TableRow>
                <SortableTableHeader
                  label="入场 / 退出 UTC"
                  :description="[metricHint('crypto', '入场 / 退出 UTC'), '按入场时间排序'].filter(Boolean).join('；')"
                  scope="crypto"
                  v-bind="tradeTable.header('entryTime')"
                /><SortableTableHeader
                  label="持有"
                  scope="crypto"
                  v-bind="tradeTable.header('holdingSeconds')"
                /><SortableTableHeader
                  label="收益"
                  scope="crypto"
                  v-bind="tradeTable.header('realizedReturn')"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="item in tradeTable.sorted.slice(0, 10)"
                :key="item.entryTime"
              >
                <TableCell>{{ item.entryTime.replace('T', ' ').slice(0, 16) }}<br>{{ item.exitTime.replace('T', ' ').slice(0, 16) }}</TableCell><TableCell>{{ (item.holdingSeconds / 3600).toFixed(2) }}h</TableCell><TableCell>{{ percent(item.realizedReturn) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>
      </div>
    </CardContent>
  </Card>
</template>
