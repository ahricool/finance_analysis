<script setup lang="ts">
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useQuantTableSort } from '@/composables/useQuantTableSort';
import StockLink from '@/components/stocks/StockLink.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import type { QuantSignal } from '@/types/quant';
import PageHeader from '@/components/layout/PageHeader.vue';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketScoreBreakdown from '@/components/quant/MarketScoreBreakdown.vue';
import MarketScoreChart from '@/components/quant/MarketScoreChart.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { MarketRegime, QuantCapabilities, SignalRanking } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatRealizedReturn, formatScore, regimeLabels } from '@/utils/quant';
import { onBeforeUnmount, ref, watch } from 'vue';

const { market, marketQuery, tradeDate } = useQuantMarket();
const capability = ref<QuantCapabilities | null>(null);
const regime = ref<MarketRegime | null>(null);
const history = ref<MarketRegime[]>([]);
const selected = ref<QuantSignal | null>(null);
const dialogOpen = ref(false);
function show(item: QuantSignal) { selected.value = item; dialogOpen.value = true; }
const ranking = ref<SignalRanking | null>(null);
const loading = ref(true);
const error = ref<ParsedApiError | null>(null);
let requestVersion = 0;

watch(
  [market, tradeDate],
  async ([current, date]) => {
    const version = ++requestVersion;
    selected.value = null; dialogOpen.value = false;
    capability.value = null;
    regime.value = null;
    history.value = [];
    ranking.value = null;
    error.value = null;
    loading.value = true;
    try {
      const signals = await quantApi.signals(current, date || undefined);
      if (version !== requestVersion) return;
      ranking.value = signals;
      const actualDate = signals.tradeDate || date || undefined;
      const results = await Promise.allSettled([
        quantApi.capabilities(current),
        quantApi.marketRegime(current, actualDate, signals.modelVersion?.startsWith('batch-') ? signals.modelVersion : undefined),
        quantApi.marketRegimeHistory(current, actualDate),
      ]);
      if (version !== requestVersion) return;
      if (results[0].status === 'fulfilled') capability.value = results[0].value;
      if (results[1].status === 'fulfilled') regime.value = results[1].value;
      if (results[2].status === 'fulfilled') history.value = results[2].value;
      const failed = results.find(result => result.status === 'rejected');
      if (failed?.status === 'rejected') error.value = getParsedApiError(failed.reason);
    } catch (cause) { if (version === requestVersion) error.value = getParsedApiError(cause); }
    if (version !== requestVersion) return;
    loading.value = false;
  },
  { immediate: true },
);
onBeforeUnmount(() => { ++requestVersion; });
const { sortKey, direction, toggle, sorted: rankedItems } = useQuantTableSort(
  () => ranking.value?.items.slice(0, 10) ?? [],
  (row, key) => key === 'name' ? row.name || row.code : row[key as keyof typeof row], 'universeRank');
const detailInitialTab = ref<'overview' | 'quant'>('quant');
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      variant="section"
      title="总览"
      en="Overview"
      description="从市场环境到个股排名，查看同一交易日的研究结果。"
    />
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <Alert
      v-if="capability?.warnings.length"
      variant="warning"
      data-testid="raw-price-warning"
    >
      <AlertTitle>数据口径提示</AlertTitle><AlertDescription class="text-current/80">
        {{ capability.warnings.join('；') }}
      </AlertDescription>
    </Alert>
    <div
      v-if="loading"
      class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
    >
      <Skeleton
        v-for="index in 8"
        :key="index"
        class="h-28 w-full"
      />
    </div>
    <template v-else>
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="市场状态"
                compact
              />
            </CardDescription><CardTitle class="text-2xl">
              {{ regime ? regimeLabels[regime.regime] : '数据不可用' }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="市场得分"
                compact
              />
            </CardDescription><CardTitle class="text-2xl">
              {{ formatScore(regime?.marketScore) }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="建议最大仓位"
                compact
              />
            </CardDescription><CardTitle class="text-2xl">
              {{ formatPercent(regime?.maxEquityExposure) }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="模型 / 行情日期"
                compact
              />
            </CardDescription><CardTitle class="text-base">
              {{ ranking?.releaseId ? `模型组 #${ranking.releaseId}` : ranking?.modelVersion ?? '—' }}
            </CardTitle><p class="text-xs text-muted-foreground">
              {{ ranking?.tradeDate ?? '—' }}
            </p>
          </CardHeader>
        </Card>
      </section>
      <div class="grid items-start gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>市场得分拆解</CardTitle>
            <CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="原始指标先标准化到 0–1，再按权重汇总；贡献之和等于市场得分。"
                compact
              />
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MarketScoreBreakdown
              v-if="regime?.scoreBreakdown"
              :breakdown="regime.scoreBreakdown"
            />
            <Empty
              v-else
              data-testid="market-score-breakdown-empty"
            >
              <EmptyHeader>
                <EmptyTitle>暂无市场得分拆解</EmptyTitle>
                <EmptyDescription>旧版历史快照仍可读取，但没有保存结构化评分分项。</EmptyDescription>
              </EmptyHeader>
            </Empty>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>市场得分历史</CardTitle><CardDescription>
              <IndicatorHelpLabel
                scope="quant"
                label="观察市场状态的时间序列变化。"
                compact
              />
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MarketScoreChart
              v-if="history.length"
              :items="history"
            /><Empty v-else>
              <EmptyHeader><EmptyTitle>暂无市场状态历史</EmptyTitle></EmptyHeader>
            </Empty>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>个股排名</CardTitle><CardDescription>{{ tradeDate ? `${tradeDate} 的股票评分。` : '生产模型生成的最新股票评分。' }}</CardDescription><CardAction>
            <RouterLink
              :to="{ path: '/research/quant/signals', query: marketQuery() }"
              class="text-xs font-medium underline-offset-4 hover:underline"
            >
              查看全部
            </RouterLink>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div
            v-if="ranking?.items.length"
            class="overflow-x-auto"
          >
            <Table class="w-full min-w-[800px] text-sm">
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
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="item in rankedItems"
                  :key="item.id"
                  class="cursor-pointer border-t border-border"
                  tabindex="0"
                  @click="detailInitialTab = 'quant'; show(item)"
                  @keydown.enter.self="detailInitialTab = 'quant'; show(item)"
                  @keydown.space.self.prevent="detailInitialTab = 'quant'; show(item)"
                >
                  <TableCell class="p-2">
                    {{ item.universeRank ?? '—' }}
                  </TableCell>
                  <TableCell>
                    <StockLink
                      :code="item.code"
                      :name="item.name"
                      :market="market"
                      @select="detailInitialTab = 'overview'; show(item)"
                    />
                  </TableCell>
                  <TableCell class="text-right tabular-nums">
                    {{ formatScore(item.finalScore) }}
                  </TableCell>
                  <TableCell class="text-right tabular-nums">
                    {{ formatScore(item.crossSectionScore) }}
                  </TableCell>
                  <TableCell class="text-right tabular-nums">
                    {{ formatScore(item.timeSeriesScore) }}
                  </TableCell>
                  <TableCell class="text-right tabular-nums">
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
                  <TableCell>{{ item.signal }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
          <Empty
            v-else
            data-testid="quant-empty-state"
          >
            <EmptyHeader><EmptyTitle>{{ tradeDate ? '所选日期暂无模型排名' : market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>{{ tradeDate ? '请选择其他交易日，或清空日期查看最新数据。' : market === 'CN' ? '请先完成A股数据集构建、模型训练、人工发布和日频流水线。' : '生产模型、数据集或当日预测尚不可用。' }}</EmptyDescription></EmptyHeader>
          </Empty>
        </CardContent>
      </Card>
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
