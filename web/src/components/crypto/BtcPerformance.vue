<script setup lang="ts">
import { computed } from 'vue';
import type { CryptoPerformance } from '@/types/crypto';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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
</script>
<template>
  <Card data-testid="btc-performance">
    <CardHeader>
      <CardTitle>Performance</CardTitle>
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
            {{ label }}
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
            Recent Executions
          </h4>
          <p
            v-if="!performance.recentExecutions.length"
            class="text-sm text-muted-foreground"
          >
            暂无完整仓位变化
          </p>
          <Table v-else>
            <TableHeader><TableRow><TableHead>时间 UTC</TableHead><TableHead>操作</TableHead><TableHead>仓位</TableHead><TableHead>价格</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow
                v-for="item in performance.recentExecutions.slice(0, 10)"
                :key="item.evaluatedAt"
              >
                <TableCell>{{ item.evaluatedAt.replace('T', ' ').slice(0, 16) }}</TableCell><TableCell>{{ item.action }}</TableCell><TableCell>{{ percent(item.positionBefore) }} → {{ percent(item.positionAfter) }}</TableCell><TableCell>{{ number(item.price) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>
        <section>
          <h4 class="mb-2 font-medium">
            Recent Trades
          </h4>
          <p
            v-if="!performance.recentTrades.length"
            class="text-sm text-muted-foreground"
          >
            暂无完整持仓周期
          </p>
          <Table v-else>
            <TableHeader><TableRow><TableHead>入场 / 退出 UTC</TableHead><TableHead>持有</TableHead><TableHead>收益</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow
                v-for="item in performance.recentTrades.slice(0, 10)"
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
