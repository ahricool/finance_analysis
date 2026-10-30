<script setup lang="ts">
import { formatRank } from '@/utils/rank';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useQuantTableSort } from '@/composables/useQuantTableSort';
import StockLink from '@/components/stocks/StockLink.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { Portfolio } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { ref, watch } from 'vue';

const { market, tradeDate } = useQuantMarket();
const item = ref<Portfolio | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
let requestVersion = 0;

watch(
  [market, tradeDate],
  async ([current, date]) => {
    const version = ++requestVersion;
    item.value = null;
    error.value = null;
    loading.value = true;
    const results = await Promise.allSettled([(date ? quantApi.portfolio(current, date) : quantApi.portfolio(current))]);
    if (version !== requestVersion) return;
    if (results[0].status === 'fulfilled') item.value = results[0].value;
    else error.value = getParsedApiError(results[0].reason);
    loading.value = false;
  },
  { immediate: true },
);
const { sortKey, direction, toggle, sorted: positions } = useQuantTableSort(
  () => item.value?.items ?? [],
  (row, key) => key === 'name' ? row.name || row.code : row[key as keyof typeof row], 'rank');
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      variant="section"
      title="模型目标组合"
      en="Target Portfolio"
      description="由当日模型排名生成，不读取真实用户持仓，也不执行券商订单。"
    />
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
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="交易日"
                compact
              />
            </CardDescription><CardTitle>{{ item.tradeDate }}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="目标总仓位"
                compact
              />
            </CardDescription><CardTitle>{{ formatPercent(item.targetEquityExposure) }}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="最大总仓位"
                compact
              />
            </CardDescription><CardTitle>{{ formatPercent(item.maxEquityExposure) }}</CardTitle>
          </CardHeader>
        </Card>
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
        <CardHeader>
          <CardTitle>目标持仓</CardTitle><CardDescription>
            <IndicatorHelpLabel
              scope="quant"
              label="展示模型建议的目标权重和信号得分。"
              compact
            />
          </CardDescription>
        </CardHeader>
        <CardContent class="block">
          <Table class="w-full min-w-[900px] text-sm">
            <TableHeader>
              <TableRow>
                <SortableTableHeader
                  label="股票"
                  scope="quant"
                  :active="sortKey === 'name'"
                  :direction="direction"
                  @sort="toggle('name')"
                />
                <SortableTableHeader
                  label="排名"
                  scope="quant"
                  :active="sortKey === 'rank'"
                  :direction="direction"
                  @sort="toggle('rank')"
                />
                <SortableTableHeader
                  label="目标权重"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'targetWeight'"
                  :direction="direction"
                  @sort="toggle('targetWeight')"
                />
                <SortableTableHeader
                  label="信号"
                  scope="quant"
                  :active="sortKey === 'signal'"
                  :direction="direction"
                  @sort="toggle('signal')"
                />
                <SortableTableHeader
                  label="得分"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'finalScore'"
                  :direction="direction"
                  @sort="toggle('finalScore')"
                />
                <SortableTableHeader
                  label="预测收益"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'predictedReturn'"
                  :direction="direction"
                  @sort="toggle('predictedReturn')"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="row in positions"
                :key="row.id"
                class="border-t border-border"
              >
                <TableCell class="p-3">
                  <StockLink
                    :code="row.code"
                    :name="row.name"
                    :market="market"
                    :context="{ tradeDate: item.tradeDate }"
                  />
                </TableCell>
                <TableCell>{{ formatRank(row.rank, item.rankTotal) }}</TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatPercent(row.targetWeight) }}
                </TableCell>
                <TableCell>{{ row.signal }}</TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatScore(row.finalScore) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatPredictedReturn(row.predictedReturn) }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </template>
    <Empty v-else>
      <EmptyHeader><EmptyTitle>{{ tradeDate ? '所选日期暂无目标组合' : market === 'CN' ? 'A股目标组合尚未就绪' : '暂无目标组合' }}</EmptyTitle><EmptyDescription>{{ tradeDate ? '请选择其他交易日，或清空日期查看最新数据。' : '当前市场尚未生成可展示的模型目标组合。' }}</EmptyDescription></EmptyHeader>
    </Empty>
  </div>
</template>
