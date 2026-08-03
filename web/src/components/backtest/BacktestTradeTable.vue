<script setup lang="ts">
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { BacktestTrade } from '@/types/backtests';
import { formatMoney, formatPct } from '@/utils/backtests';

defineProps<{ trades: BacktestTrade[] }>();
</script>

<template>
  <section class="overflow-hidden rounded-xl border bg-card">
    <div class="border-b border-border/70 px-4 py-3">
      <h3 class="text-sm font-semibold text-foreground">
        交易明细
      </h3>
    </div>
    <div
      v-if="!trades.length"
      class="p-8 text-center text-sm text-muted-foreground"
    >
      本次回测没有成交
    </div>
    <div
      v-else
      class="min-w-0"
    >
      <div class="space-y-3 p-3 md:hidden">
        <article
          v-for="trade in trades"
          :key="trade.id"
          class="rounded-xl border bg-background p-4 text-xs"
        >
          <div class="flex items-center justify-between gap-3">
            <p class="font-medium">
              {{ trade.tradeDate }}
            </p>
            <Badge :variant="trade.side === 'buy' ? 'destructive' : 'success'">
              {{ trade.side === 'buy' ? '买入' : '卖出' }}
            </Badge>
          </div>
          <dl class="mt-3 grid grid-cols-2 gap-3 border-y py-3">
            <div>
              <dt class="text-muted-foreground">
                数量 / 价格
              </dt>
              <dd class="mt-1">
                {{ trade.quantity }} / {{ formatMoney(trade.price) }}
              </dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                成交金额
              </dt>
              <dd class="mt-1">
                {{ formatMoney(trade.grossAmount) }}
              </dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                总费用
              </dt>
              <dd class="mt-1">
                {{ formatMoney(trade.totalFee) }}
              </dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                收益
              </dt>
              <dd class="mt-1">
                {{ formatPct(trade.returnPct) }}
              </dd>
            </div>
          </dl>
          <p class="mt-3 text-muted-foreground">
            交易后现金 {{ formatMoney(trade.cashAfter) }} · 持仓 {{ trade.positionAfter }}
          </p>
        </article>
      </div>
      <div class="hidden overflow-x-auto md:block">
        <Table class="min-w-[1100px] w-full text-left text-xs">
          <TableHeader class="bg-card/60 text-muted-foreground">
            <TableRow>
              <TableHead class="p-3">
                信号日期
              </TableHead>
              <TableHead class="p-3">
                成交日期
              </TableHead>
              <TableHead class="p-3">
                方向
              </TableHead>
              <TableHead class="p-3">
                数量
              </TableHead>
              <TableHead class="p-3">
                价格
              </TableHead>
              <TableHead class="p-3">
                金额
              </TableHead>
              <TableHead class="p-3">
                佣金
              </TableHead>
              <TableHead class="p-3">
                税费
              </TableHead>
              <TableHead class="p-3">
                总费用
              </TableHead>
              <TableHead class="p-3">
                交易后现金
              </TableHead>
              <TableHead class="p-3">
                交易后持仓
              </TableHead>
              <TableHead class="p-3">
                收益
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody class="divide-y divide-border/60">
            <TableRow
              v-for="trade in trades"
              :key="trade.id"
            >
              <TableCell class="p-3">
                {{ trade.signalDate }}
              </TableCell>
              <TableCell class="p-3">
                {{ trade.tradeDate }}
              </TableCell>
              <TableCell class="p-3">
                <Badge :variant="trade.side === 'buy' ? 'destructive' : 'success'">
                  {{ trade.side === 'buy' ? '买入' : '卖出' }}
                </Badge>
              </TableCell>
              <TableCell class="p-3">
                {{ trade.quantity }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.price) }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.grossAmount) }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.commission) }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.tax + trade.otherFee) }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.totalFee) }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatMoney(trade.cashAfter) }}
              </TableCell>
              <TableCell class="p-3">
                {{ trade.positionAfter }}
              </TableCell>
              <TableCell class="p-3">
                {{ formatPct(trade.returnPct) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  </section>
</template>
