<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
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
      class="p-8 text-center text-sm text-muted-text"
    >
      本次回测没有成交
    </div>
    <div
      v-else
      class="overflow-x-auto"
    >
      <table class="min-w-[1100px] w-full text-left text-xs">
        <thead class="bg-elevated/60 text-muted-text">
          <tr>
            <th class="p-3">
              信号日期
            </th><th class="p-3">
              成交日期
            </th><th class="p-3">
              方向
            </th><th class="p-3">
              数量
            </th><th class="p-3">
              价格
            </th><th class="p-3">
              金额
            </th><th class="p-3">
              佣金
            </th><th class="p-3">
              税费
            </th><th class="p-3">
              总费用
            </th><th class="p-3">
              交易后现金
            </th><th class="p-3">
              交易后持仓
            </th><th class="p-3">
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
            </td><td class="p-3">
              {{ trade.tradeDate }}
            </td><td class="p-3">
              <Badge :variant="trade.side === 'buy' ? 'danger' : 'success'">
                {{ trade.side === 'buy' ? '买入' : '卖出' }}
              </Badge>
            </td><td class="p-3">
              {{ trade.quantity }}
            </td><td class="p-3">
              {{ formatMoney(trade.price) }}
            </td><td class="p-3">
              {{ formatMoney(trade.grossAmount) }}
            </td><td class="p-3">
              {{ formatMoney(trade.commission) }}
            </td><td class="p-3">
              {{ formatMoney(trade.tax + trade.otherFee) }}
            </td><td class="p-3">
              {{ formatMoney(trade.totalFee) }}
            </td><td class="p-3">
              {{ formatMoney(trade.cashAfter) }}
            </td><td class="p-3">
              {{ trade.positionAfter }}
            </td><td class="p-3">
              {{ formatPct(trade.returnPct) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
