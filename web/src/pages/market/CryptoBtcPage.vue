<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { useBinanceBtcMarket } from '@/composables/useBinanceBtcMarket';
import { useCryptoStrategy } from '@/composables/useCryptoStrategy';
import { BINANCE_INTERVALS } from '@/types/binance';
import BtcPerformance from '@/components/crypto/BtcPerformance.vue';
import BtcKlineChart from '@/components/crypto/BtcKlineChart.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

const { candles, current, price, interval, connection, loading: marketLoading, restError, wsError, refresh: refreshMarket } = useBinanceBtcMarket();
const markerRange = computed(() => {
  const first = candles.value[0] ?? current.value;
  const last = current.value ?? candles.value.at(-1);
  return first && last ? { start: first.openTime, end: last.closeTime } : null;
});
const { overview, signals, loading, error, refresh, performance, performanceError, refreshPerformance,
  selectedKey, strategies, strategiesError, refreshStrategies, summaries, markers, markerError, refreshMarkers } = useCryptoStrategy(markerRange);
const strategy = computed(() => overview.value?.strategy);
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
function percent(value: string | null) { return value == null ? '—' : Number.isFinite(Number(value) * 100) ? `${(Number(value) * 100).toFixed(2)}%` : `${value} × 100%`; }
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
          Binance 行情 · 15m 突破策略 · LONG / FLAT 为策略状态，不执行交易
        </p>
        <p class="mt-3 text-3xl font-semibold tabular-nums">
          {{ number(price) }} <span class="text-sm text-muted-foreground">USDT</span>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Badge variant="outline">
          {{ restError ? '行情加载失败' : connection === 'live' ? '实时' : connection === 'reconnecting' ? '重连中' : '连接中' }}
        </Badge>
        <Button
          variant="outline"
          aria-label="刷新 BTC 行情"
          :disabled="marketLoading"
          @click="refreshMarket()"
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
      v-if="restError || wsError"
      class="text-sm text-destructive"
      role="alert"
    >
      {{ restError || wsError }}
    </p>
    <Button
      v-if="error"
      variant="outline"
      @click="refresh()"
    >
      重试策略数据
    </Button>
    <Card>
      <CardHeader>
        <CardTitle>BTCUSDT · {{ interval }} K线</CardTitle>
        <CardDescription>红涨绿跌 · UTC · 可拖动或缩放历史区间</CardDescription>
      </CardHeader>
      <CardContent class="min-w-0 px-2 sm:px-6">
        <div
          class="mb-4 flex gap-2"
          data-testid="btc-interval-selector"
          aria-label="K线周期"
        >
          <Button
            v-for="item in BINANCE_INTERVALS"
            :key="item"
            size="sm"
            :variant="interval === item ? 'default' : 'outline'"
            :aria-pressed="interval === item"
            @click="interval = item"
          >
            {{ item === '1d' ? '1D' : item === '1w' ? '1W' : item }}
          </Button>
        </div>
        <p
          v-if="!marketLoading && !candles.length && !current"
          class="py-12 text-center text-muted-foreground"
        >
          暂无 K 线，请重试加载。
        </p>
        <AppApiErrorAlert
          v-if="markerError"
          :error="markerError"
        />
        <Button
          v-if="markerError"
          variant="outline"
          @click="refreshMarkers()"
        >
          重试策略标记
        </Button>
        <BtcKlineChart
          v-if="candles.length || current"
          :interval="interval"
          :signals="markers"
          :strategy-key="selectedKey"
          :strategy-name="strategies.find(item => item.strategyKey === selectedKey)?.displayName"
          :candles="candles"
          :current="current"
        />
      </CardContent>
    </Card>
    <AppApiErrorAlert
      v-if="strategiesError"
      :error="strategiesError"
    />
    <Button
      v-if="strategiesError"
      variant="outline"
      @click="refreshStrategies()"
    >
      重试策略列表与对比
    </Button>
    <div class="flex items-center gap-3">
      <h3 class="text-lg font-semibold">
        Strategy
      </h3>
      <select
        v-model="selectedKey"
        aria-label="Strategy"
        class="rounded border bg-background px-3 py-2 text-sm"
      >
        <option
          v-if="!strategies.length"
          value="btc_breakout_v1"
        >
          Breakout V1
        </option>
        <option
          v-for="item in strategies"
          :key="item.strategyKey"
          :value="item.strategyKey"
        >
          {{ item.displayName }}{{ item.enabled ? '' : '（停用）' }}
        </option>
      </select>
    </div>
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
    <AppApiErrorAlert
      v-if="performanceError"
      :error="performanceError"
    />
    <Button
      v-if="performanceError"
      variant="outline"
      @click="refreshPerformance()"
    >
      重试绩效
    </Button>
    <Card
      v-if="summaries.length >= 2"
      data-testid="btc-strategy-comparison"
    >
      <CardHeader><CardTitle>Strategy Comparison</CardTitle></CardHeader>
      <CardContent class="overflow-x-auto">
        <Table>
          <TableHeader><TableRow><TableHead>Strategy</TableHead><TableHead>Position</TableHead><TableHead>Total</TableHead><TableHead>Annualized</TableHead><TableHead>MDD</TableHead><TableHead>Win Rate</TableHead><TableHead>Days</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow
              v-for="item in summaries"
              :key="item.strategyKey"
            >
              <TableCell>{{ item.displayName }}</TableCell><TableCell>{{ percent(item.currentPosition.positionPct) }}</TableCell><TableCell>{{ percent(item.totalReturn) }}</TableCell><TableCell>{{ percent(item.annualizedReturn) }}</TableCell><TableCell>{{ percent(item.maxDrawdown) }}</TableCell><TableCell>{{ percent(item.winRate) }}</TableCell><TableCell>{{ number(item.runningDays) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
    <BtcPerformance
      v-if="performance"
      :performance="performance"
      :price="price"
    />
  </div>
</template>
