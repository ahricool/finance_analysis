<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { useCryptoBtc } from '@/composables/useCryptoBtc';
import BtcKlineChart from '@/components/crypto/BtcKlineChart.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

const { candles, current, overview, signals, status, connection, loading, error, refresh } = useCryptoBtc();
const strategy = computed(() => overview.value?.strategy);
const price = computed(() => current.value?.close ?? candles.value.at(-1)?.close ?? strategy.value?.price);
const metrics = computed(() => [
  ['Market Regime', strategy.value?.regime ?? '等待数据'],
  ['Setup', strategy.value?.setup ?? '—'],
  ['Action', strategy.value?.action ?? '—'],
  ['Strategy State', strategy.value?.positionState ?? overview.value?.state.positionState ?? 'FLAT'],
  ['EMA20 · 1h', number(strategy.value?.ema201H)],
  ['EMA50 · 1h', number(strategy.value?.ema501H)],
  ['Breakout Level · 15m', number(strategy.value?.breakoutLevel15M)],
  ['Volume Ratio · 15m', number(strategy.value?.volumeRatio15M)],
  ['ATR14 · 15m', number(strategy.value?.atr1415M)],
  ['Initial Stop', number(strategy.value?.initialStop)],
  ['Trailing Stop', number(strategy.value?.trailingStop)],
]);
const fallback = computed(() => connection.value === 'http_fallback' || status.value?.streamMode === 'http_fallback');
function number(value: string | null | undefined) {
  return value == null ? '—' : Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
}
function time(value: string | null | undefined) {
  return value ? new Date(value).toISOString().replace('T', ' ').slice(0, 19) + ' UTC' : '—';
}
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="crypto-btc-page"
  >
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-xl font-semibold">
          BTCUSDT <span class="text-sm text-muted-foreground">Binance Spot</span>
        </h2>
        <p class="mt-1 text-sm text-muted-foreground">
          1m 行情 · 15m 突破策略 · LONG / FLAT 为策略状态，不执行交易
        </p>
        <p class="mt-3 text-3xl font-semibold tabular-nums">
          {{ number(price) }} <span class="text-sm text-muted-foreground">USDT</span>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Badge variant="outline">
          {{ status?.enabled === false ? '已停用' : !status?.ready ? '同步中' : fallback ? 'HTTP 兜底' : connection === 'websocket' ? '实时' : '连接中' }}
        </Badge>
        <Button
          variant="outline"
          aria-label="刷新 BTC 行情"
          :disabled="loading"
          @click="refresh(1000)"
        >
          <RefreshCcw class="size-4" />
        </Button>
      </div>
    </header>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="connection === 'unauthorized'"
      class="text-sm text-muted-foreground"
    >
      登录已失效，请重新登录。
    </p>
    <p
      v-else-if="fallback"
      class="text-sm text-muted-foreground"
      data-testid="crypto-fallback"
    >
      行情实时连接中断，当前使用分钟级备用行情
    </p>
    <p
      v-if="status && !status.ready && status.enabled"
      class="text-sm text-muted-foreground"
    >
      正在等待行情进程同步历史数据。
    </p>
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card
        v-for="[label, value] in metrics"
        :key="label"
      >
        <CardHeader class="pb-2">
          <CardDescription>{{ label }}</CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton
            v-if="loading"
            class="h-6 w-20"
          /><strong
            v-else
            class="text-lg tabular-nums"
          >{{ value }}</strong>
        </CardContent>
      </Card>
    </div>
    <Card>
      <CardHeader>
        <CardTitle>BTCUSDT · 1m K线</CardTitle>
        <CardDescription>红涨绿跌 · UTC · 最新行情 {{ time(status?.lastUpdateTime) }} · 可拖动或缩放历史区间</CardDescription>
      </CardHeader>
      <CardContent class="min-w-0 px-2 sm:px-6">
        <p
          v-if="!loading && !candles.length && !current"
          class="py-12 text-center text-muted-foreground"
        >
          暂无 K 线，等待行情同步。
        </p>
        <BtcKlineChart
          v-else
          :candles="candles"
          :current="current"
        />
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>Recent Signals</CardTitle><CardDescription>{{ strategy?.reason ?? '等待完整 1h EMA50 与 15m 指标预热。' }} · 每 15 分钟收盘后评估</CardDescription></CardHeader>
      <CardContent class="min-w-0 overflow-x-auto">
        <p
          v-if="!signals.length"
          class="py-6 text-center text-muted-foreground"
        >
          暂无策略快照
        </p>
        <Table v-else>
          <TableHeader><TableRow><TableHead>时间 UTC</TableHead><TableHead>Action</TableHead><TableHead>Regime</TableHead><TableHead>Price</TableHead><TableHead>State</TableHead><TableHead>原因</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow
              v-for="item in signals"
              :key="item.evaluatedAt"
            >
              <TableCell class="whitespace-nowrap">
                {{ time(item.evaluatedAt) }}
              </TableCell><TableCell>
                <Badge variant="outline">
                  {{ item.action }}
                </Badge>
              </TableCell><TableCell>{{ item.regime }}</TableCell><TableCell>{{ number(item.price) }}</TableCell><TableCell>{{ item.positionState }}</TableCell><TableCell class="min-w-56 whitespace-normal">
                {{ item.reason }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
