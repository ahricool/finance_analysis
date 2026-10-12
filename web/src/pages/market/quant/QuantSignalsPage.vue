<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import type { QuantSignal } from '@/types/quant';
import { Button } from '@/components/ui/button';
import PageHeader from '@/components/layout/PageHeader.vue';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { SignalRanking } from '@/types/quant';
import { formatPredictedReturn, formatRealizedReturn, formatScore } from '@/utils/quant';
import { formatSecurityLabel } from '@/utils/security';
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const { market, tradeDate } = useQuantMarket();
const selected = ref<QuantSignal | null>(null);
const dialogOpen = ref(false);
function show(item: QuantSignal) { selected.value = item; dialogOpen.value = true; }
const ranking = ref<SignalRanking | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const filter = ref('');
const items = computed(
  () =>
    ranking.value?.items.filter(
      (item) =>
        (!filter.value ||
          item.code.includes(filter.value.toUpperCase()) ||
          item.name?.toLowerCase().includes(filter.value.toLowerCase())),
    ) ?? [],
);
let requestVersion = 0;

watch(
  [market, tradeDate],
  async ([current, date]) => {
    const version = ++requestVersion;
    selected.value = null; dialogOpen.value = false;
    ranking.value = null;
    error.value = null;
    loading.value = true;
    try {
      const value = await (date ? quantApi.signals(current, date) : quantApi.signals(current));
      if (version === requestVersion) ranking.value = value;
    } catch (err) {
      if (version === requestVersion) error.value = getParsedApiError(err);
    } finally {
      if (version === requestVersion) loading.value = false;
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => { ++requestVersion; });
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      variant="section"
      title="模型选股排名"
      en="Model Signals"
      :description="`模型预测仅用于研究和生成目标组合，不代表真实订单。${ranking?.modelVersion ? `当前版本：${ranking.modelVersion}。` : ''}`"
    />
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="space-y-3"
    >
      <Skeleton
        v-for="index in 5"
        :key="index"
        class="h-14 w-full"
      />
    </div>
    <template v-else>
      <Card>
        <CardHeader>
          <CardTitle>筛选排名</CardTitle><CardDescription>
            <IndicatorHelpLabel
              scope="quant"
              label="按股票代码或名称缩小结果范围。"
              compact
            />
          </CardDescription>
        </CardHeader><CardContent>
          <FieldInput
            v-model="filter"
            placeholder="股票代码或名称"
          />
        </CardContent>
      </Card>
      <Card
        v-if="items.length"
      >
        <CardHeader><CardTitle>模型排名</CardTitle><CardDescription>{{ ranking?.tradeDate || '—' }} · 共 {{ items.length }} 个标的。</CardDescription></CardHeader>
        <CardContent class="block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="排名"
                    compact
                  />
                </TableHead><TableHead class="min-w-[220px]">
                  <IndicatorHelpLabel
                    scope="quant"
                    label="股票"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="最终得分"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="横截面"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="时间序列"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="风险扣分"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="预测收益"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="3D收益"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="5D收益"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="至今收益"
                    compact
                  />
                </TableHead><TableHead>
                  <IndicatorHelpLabel
                    scope="quant"
                    label="信号"
                    compact
                  />
                </TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="item in items"
                :key="item.id"
              >
                <TableCell>{{ item.universeRank ?? '—' }}</TableCell>
                <TableCell>
                  <Button
                    variant="link"
                    class="font-medium rounded-sm underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    @click="show(item)"
                  >
                    {{ formatSecurityLabel(item.code, item.name) }}
                  </Button>
                </TableCell><TableCell>{{ formatScore(item.finalScore) }}</TableCell><TableCell>{{ formatScore(item.crossSectionScore) }}</TableCell><TableCell>{{ formatScore(item.timeSeriesScore) }}</TableCell><TableCell>{{ formatScore(item.riskPenalty) }}</TableCell><TableCell>{{ formatPredictedReturn(item.predictedReturn) }}</TableCell>
                <TableCell>{{ formatRealizedReturn(item.return3D) }}</TableCell>
                <TableCell>{{ formatRealizedReturn(item.return5D) }}</TableCell>
                <TableCell>{{ formatRealizedReturn(item.returnSince) }}</TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {{ item.signal }}
                  </Badge>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Empty v-else>
        <EmptyHeader><EmptyTitle>{{ tradeDate ? '所选日期暂无模型排名' : market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>{{ tradeDate ? '请选择其他交易日，或清空日期查看最新数据。' : '当前市场没有可展示的生产模型信号。' }}</EmptyDescription></EmptyHeader>
      </Empty>
    </template>
    <StockDetailDialog
      v-model:open="dialogOpen"
      :stock="selected ? { code: selected.code, name: selected.name || '', market_type: market } : null"
      kind="research"
      initial-tab="quant"
      :context="{ tradeDate: selected?.tradeDate || ranking?.tradeDate || tradeDate || undefined, view: 'official' }"
    />
  </div>
</template>
