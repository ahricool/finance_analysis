<script setup lang="ts">
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useQuantTableSort } from '@/composables/useQuantTableSort';
import StockLink from '@/components/stocks/StockLink.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import type { QuantSignal } from '@/types/quant';
import PageHeader from '@/components/layout/PageHeader.vue';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { exportExcel } from '@/utils/excelExport';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { SignalRanking } from '@/types/quant';
import { formatPredictedReturn, formatRealizedReturn, formatScore } from '@/utils/quant';
import { onBeforeUnmount, ref, watch } from 'vue';

const { market, tradeDate } = useQuantMarket();
const selected = ref<QuantSignal | null>(null);
const dialogOpen = ref(false);
function show(item: QuantSignal) { selected.value = item; dialogOpen.value = true; }
const ranking = ref<SignalRanking | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const filter = ref('');
const signalFilter = ref('all');
const { sortKey, direction, toggle, sorted: items } = useQuantTableSort(
  () => (ranking.value?.items ?? []).filter(item =>
    (signalFilter.value === 'all' || item.signal === signalFilter.value) &&
    (!filter.value || item.code.includes(filter.value.toUpperCase()) || item.name?.toLowerCase().includes(filter.value.toLowerCase()))),
  (row, key) => key === 'name' ? row.name || row.code : row[key as keyof typeof row], 'universeRank');
const exporting = ref(false);
async function exportRanking() {
  if (exporting.value || !items.value.length) return;
  exporting.value=true;
  try {
    await exportExcel(`Quant_${market.value}_${ranking.value?.tradeDate}.xlsx`, '个股排名',
      ['日期','代码','名称','原排名','综合分','横截面分','时间序列分','预测收益（百分点）','信号'].map(label => ({label})),
      items.value.map(item => [item.tradeDate,item.code,item.name,item.universeRank,item.finalScore,item.crossSectionScore,item.timeSeriesScore,item.predictedReturn,item.signal]));
  } catch(cause) { error.value=getParsedApiError(cause); }
  finally {exporting.value=false;}
}
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
const detailInitialTab = ref<'overview' | 'quant'>('quant');
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      variant="section"
      title="个股排名"
      en="Stock Rankings"
      :description="`模型预测仅用于研究和生成目标组合，不代表真实订单。${ranking?.releaseId ? `模型组 #${ranking.releaseId}。` : ''}`"
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
        <CardContent class="quant-filters">
          <FieldInput
            v-model="filter"
            label="搜索股票"
            placeholder="股票代码或名称"
          />
          <div class="flex flex-wrap items-end gap-3">
            <FieldSelect
              v-model="signalFilter"
              label="信号筛选"
              :options="[{value:'all',label:'全部'}, {value:'buy',label:'买入'}, {value:'watch',label:'观察'}, {value:'hold',label:'持有'}, {value:'avoid',label:'回避'}]"
            />
            <Button
              :disabled="exporting || !items.length"
              variant="outline"
              @click="exportRanking"
            >
              导出筛选结果
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card
        v-if="items.length"
      >
        <CardHeader><CardTitle>排名明细</CardTitle><CardDescription>{{ ranking?.tradeDate || '—' }} · 共 {{ items.length }} 个标的。</CardDescription></CardHeader>
        <CardContent class="block">
          <Table>
            <TableHeader>
              <TableRow>
                <SortableTableHeader
                  label="排名"
                  scope="quant"
                  :active="sortKey === 'universeRank'"
                  :direction="direction"
                  @sort="toggle('universeRank')"
                />
                <SortableTableHeader
                  label="股票"
                  scope="quant"
                  :active="sortKey === 'name'"
                  :direction="direction"
                  @sort="toggle('name')"
                />
                <SortableTableHeader
                  label="最终得分"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'finalScore'"
                  :direction="direction"
                  @sort="toggle('finalScore')"
                />
                <SortableTableHeader
                  label="横截面"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'crossSectionScore'"
                  :direction="direction"
                  @sort="toggle('crossSectionScore')"
                />
                <SortableTableHeader
                  label="时间序列"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'timeSeriesScore'"
                  :direction="direction"
                  @sort="toggle('timeSeriesScore')"
                />
                <SortableTableHeader
                  label="风险扣分"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'riskPenalty'"
                  :direction="direction"
                  @sort="toggle('riskPenalty')"
                />
                <SortableTableHeader
                  label="预测收益"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'predictedReturn'"
                  :direction="direction"
                  @sort="toggle('predictedReturn')"
                />
                <SortableTableHeader
                  label="3D收益"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'return3D'"
                  :direction="direction"
                  @sort="toggle('return3D')"
                />
                <SortableTableHeader
                  label="5D收益"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'return5D'"
                  :direction="direction"
                  @sort="toggle('return5D')"
                />
                <SortableTableHeader
                  label="至今收益"
                  scope="quant"
                  align="right"
                  :active="sortKey === 'returnSince'"
                  :direction="direction"
                  @sort="toggle('returnSince')"
                />
                <SortableTableHeader
                  label="信号"
                  scope="quant"
                  :active="sortKey === 'signal'"
                  :direction="direction"
                  @sort="toggle('signal')"
                />
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="item in items"
                :key="item.id"
                class="cursor-pointer"
                tabindex="0"
                @click="detailInitialTab = 'quant'; show(item)"
                @keydown.enter.self="detailInitialTab = 'quant'; show(item)"
                @keydown.space.self.prevent="detailInitialTab = 'quant'; show(item)"
              >
                <TableCell>{{ item.universeRank ?? '—' }}</TableCell>
                <TableCell>
                  <StockLink
                    :code="item.code"
                    :name="item.name"
                    :market="market"
                    @select="detailInitialTab = 'overview'; show(item)"
                  />
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ formatScore(item.finalScore) }}
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ formatScore(item.crossSectionScore) }}
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ formatScore(item.timeSeriesScore) }}
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ formatScore(item.riskPenalty) }}
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ formatPredictedReturn(item.predictedReturn) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatRealizedReturn(item.return3D) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatRealizedReturn(item.return5D) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ formatRealizedReturn(item.returnSince) }}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    :class="`quant-signal-${item.signal}`"
                  >
                    {{ item.signal }}
                  </Badge>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Empty v-else-if="!error">
        <EmptyHeader><EmptyTitle>{{ ranking?.items.length ? '没有匹配的股票，请清空搜索条件' : tradeDate ? '所选日期暂无模型排名' : market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>{{ tradeDate ? '请选择其他交易日，或清空日期查看最新数据。' : '当前市场没有可展示的生产模型信号。' }}</EmptyDescription></EmptyHeader>
      </Empty>
    </template>
    <StockDetailDialog
      v-model:open="dialogOpen"
      :stock="selected ? { code: selected.code, name: selected.name || '', marketType: market } : null"
      kind="research"
      :initial-tab="detailInitialTab"
      :context="{ tradeDate: selected?.tradeDate || ranking?.tradeDate || tradeDate || undefined, view: 'official' }"
    />
  </div>
</template>
