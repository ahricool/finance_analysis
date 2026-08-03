<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { IntradayConfirmation, Portfolio } from '@/types/quant';
import { actionLabels, formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { formatSecurityLabel } from '@/utils/security';
import { ref, watch } from 'vue';

const { market } = useQuantMarket();
const item = ref<Portfolio | null>(null);
const confirmations = ref<Record<string, IntradayConfirmation>>({});
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
let requestVersion = 0;
const confirmationLabels: Record<string, string> = {
  confirm: '确认入场',
  wait: '等待确认',
  reject: '拒绝入场',
  expired: '已过期',
  insufficient_data: '数据不足',
};

watch(
  market,
  async (current) => {
    const version = ++requestVersion;
    item.value = null;
    confirmations.value = {};
    error.value = null;
    loading.value = true;
    const results = await Promise.allSettled([quantApi.portfolio(current)]);
    if (version !== requestVersion) return;
    if (results[0].status === 'fulfilled') item.value = results[0].value;
    else error.value = getParsedApiError(results[0].reason);
    if (item.value) {
      const confirmationResults = await Promise.allSettled([
        quantApi.confirmations(current, item.value.id),
      ]);
      if (version !== requestVersion) return;
      if (confirmationResults[0].status === 'fulfilled') {
        confirmations.value = Object.fromEntries(
          confirmationResults[0].value.map((row) => [row.code, row]),
        );
      }
    }
    loading.value = false;
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        组合建议
      </h2>
      <p class="text-xs text-muted-foreground">
        研究建议，不执行真实券商订单，也不保证收益。
      </p>
    </header>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="grid gap-3 sm:grid-cols-3"
    >
      <Skeleton
        v-for="index in 6"
        :key="index"
        class="h-24 w-full"
      />
    </div>
    <template v-else-if="item">
      <section class="grid gap-3 sm:grid-cols-3">
        <Card><CardHeader><CardDescription>交易日</CardDescription><CardTitle>{{ item.tradeDate }}</CardTitle></CardHeader></Card>
        <Card><CardHeader><CardDescription>目标总仓位</CardDescription><CardTitle>{{ formatPercent(item.targetEquityExposure) }}</CardTitle></CardHeader></Card>
        <Card><CardHeader><CardDescription>最大总仓位</CardDescription><CardTitle>{{ formatPercent(item.maxEquityExposure) }}</CardTitle></CardHeader></Card>
      </section>
      <Alert
        v-if="item.warnings.length"
        variant="warning"
      >
        <AlertTitle>组合约束提示</AlertTitle><AlertDescription class="text-current/80">
          {{ item.warnings.join('；') }}
        </AlertDescription>
      </Alert>
      <Card>
        <CardHeader><CardTitle>调仓建议</CardTitle><CardDescription>展示目标权重、信号得分和分钟级确认结果。</CardDescription></CardHeader>
        <CardContent class="hidden md:block">
          <Table class="w-full min-w-[900px] text-sm">
            <TableHeader class="text-left text-xs text-muted-foreground">
              <TableRow>
                <TableHead class="min-w-[220px] p-3">
                  股票
                </TableHead>
                <TableHead>行业</TableHead>
                <TableHead>动作</TableHead>
                <TableHead>当前权重</TableHead>
                <TableHead>目标权重</TableHead>
                <TableHead>变化</TableHead>
                <TableHead>得分</TableHead>
                <TableHead>预测收益</TableHead>
                <TableHead>分钟确认</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="row in item.items"
                :key="row.id"
                class="border-t border-border"
              >
                <TableCell class="p-3">
                  {{ formatSecurityLabel(row.code, row.name) }}
                </TableCell>
                <TableCell>{{ row.sectorKey ?? '—' }}</TableCell>
                <TableCell>{{ actionLabels[row.action] ?? row.action }}</TableCell>
                <TableCell>{{ formatPercent(row.currentWeight) }}</TableCell>
                <TableCell>{{ formatPercent(row.targetWeight) }}</TableCell>
                <TableCell>{{ formatPercent(row.weightChange) }}</TableCell>
                <TableCell>{{ formatScore(row.finalScore) }}</TableCell>
                <TableCell>{{ formatPredictedReturn(row.predictedReturn) }}</TableCell>
                <TableCell>
                  <span>{{
                    confirmationLabels[confirmations[row.code]?.decision] ?? '等待确认'
                  }}</span>
                  <details
                    v-if="confirmations[row.code]"
                    class="text-xs text-muted-foreground"
                  >
                    <summary>确认详情</summary>
                    <p>
                      价格 {{ formatScore(confirmations[row.code].price) }} / VWAP
                      {{ formatScore(confirmations[row.code].vwap) }}
                    </p>
                    <p>{{ confirmations[row.code].reasons.join('；') }}</p>
                  </details>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
        <CardContent class="space-y-3 md:hidden">
          <Card
            v-for="row in item.items"
            :key="row.id"
          >
            <CardHeader>
              <CardTitle class="text-base">
                {{ formatSecurityLabel(row.code, row.name) }}
              </CardTitle><CardDescription>{{ row.sectorKey ?? '未分类' }}</CardDescription><Badge variant="outline">
                {{ actionLabels[row.action] ?? row.action }}
              </Badge>
            </CardHeader><CardContent class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p class="text-xs text-muted-foreground">
                  目标权重
                </p>{{ formatPercent(row.targetWeight) }}
              </div><div>
                <p class="text-xs text-muted-foreground">
                  预测收益
                </p>{{ formatPredictedReturn(row.predictedReturn) }}
              </div>
            </CardContent>
          </Card>
        </CardContent>
      </Card>
    </template>
    <Empty v-else>
      <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股组合建议尚未就绪' : '暂无组合建议' }}</EmptyTitle><EmptyDescription>当前市场尚未生成可展示的组合建议。</EmptyDescription></EmptyHeader>
    </Empty>
  </div>
</template>
