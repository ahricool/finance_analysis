<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { Portfolio } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { formatSecurityLabel } from '@/utils/security';
import { ref, watch } from 'vue';

const { market } = useQuantMarket();
const item = ref<Portfolio | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
let requestVersion = 0;

watch(
  market,
  async (current) => {
    const version = ++requestVersion;
    item.value = null;
    error.value = null;
    loading.value = true;
    const results = await Promise.allSettled([quantApi.portfolio(current)]);
    if (version !== requestVersion) return;
    if (results[0].status === 'fulfilled') item.value = results[0].value;
    else error.value = getParsedApiError(results[0].reason);
    loading.value = false;
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        模型目标组合
      </h2>
      <p class="text-xs text-muted-foreground">
        由当日模型排名生成，不读取真实用户持仓，也不执行券商订单。
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
        <CardHeader><CardTitle>目标持仓</CardTitle><CardDescription>展示模型建议的目标权重和信号得分。</CardDescription></CardHeader>
        <CardContent class="block">
          <Table class="w-full min-w-[900px] text-sm">
            <TableHeader class="text-left text-xs text-muted-foreground">
              <TableRow>
                <TableHead class="min-w-[220px] p-3">
                  股票
                </TableHead>
                <TableHead>排名</TableHead>
                <TableHead>目标权重</TableHead>
                <TableHead>信号</TableHead>
                <TableHead>得分</TableHead>
                <TableHead>预测收益</TableHead>
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
                <TableCell>#{{ row.rank }}</TableCell>
                <TableCell>{{ formatPercent(row.targetWeight) }}</TableCell>
                <TableCell>{{ row.signal }}</TableCell>
                <TableCell>{{ formatScore(row.finalScore) }}</TableCell>
                <TableCell>{{ formatPredictedReturn(row.predictedReturn) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </template>
    <Empty v-else>
      <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股目标组合尚未就绪' : '暂无目标组合' }}</EmptyTitle><EmptyDescription>当前市场尚未生成可展示的模型目标组合。</EmptyDescription></EmptyHeader>
    </Empty>
  </div>
</template>
