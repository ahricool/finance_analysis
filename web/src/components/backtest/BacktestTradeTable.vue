<script setup lang="ts">
import Badge from '@/components/app/AppBadge.vue';
import type { BacktestTrade } from '@/types/backtests';
import { formatMoney, formatPct } from '@/utils/backtests';

defineProps<{ trades: BacktestTrade[] }>();
</script>

<template>
  <section class="overflow-hidden rounded-2xl border border-border/70 bg-card/94">
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
        <table class="min-w-[1100px] w-full text-left text-xs">
          <thead class="bg-card/60 text-muted-foreground">
            <tr>
              <th class="p-3">
                信号日期
              </th>
              <th class="p-3">
                成交日期
              </th>
              <th class="p-3">
                方向
              </th>
              <th class="p-3">
                数量
              </th>
              <th class="p-3">
                价格
              </th>
              <th class="p-3">
                金额
              </th>
              <th class="p-3">
                佣金
              </th>
              <th class="p-3">
                税费
              </th>
              <th class="p-3">
                总费用
              </th>
              <th class="p-3">
                交易后现金
              </th>
              <th class="p-3">
                交易后持仓
              </th>
              <th class="p-3">
                收益
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border/60">
            <tr
              v-for="trade in trades"
              :key="trade.id"
            >
              <td class="p-3">
                {{ trade.signalDate }}
              </td>
              <td class="p-3">
                {{ trade.tradeDate }}
              </td>
              <td class="p-3">
                <Badge :variant="trade.side === 'buy' ? 'destructive' : 'success'">
                  {{ trade.side === 'buy' ? '买入' : '卖出' }}
                </Badge>
              </td>
              <td class="p-3">
                {{ trade.quantity }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.price) }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.grossAmount) }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.commission) }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.tax + trade.otherFee) }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.totalFee) }}
              </td>
              <td class="p-3">
                {{ formatMoney(trade.cashAfter) }}
              </td>
              <td class="p-3">
                {{ trade.positionAfter }}
              </td>
              <td class="p-3">
                {{ formatPct(trade.returnPct) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
