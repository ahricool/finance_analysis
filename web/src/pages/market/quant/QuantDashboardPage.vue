<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketScoreChart from '@/components/quant/MarketScoreChart.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { MarketRegime, QuantCapabilities, SectorRegime, SignalRanking } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore, regimeLabels } from '@/utils/quant';
import { ref, watch } from 'vue';

const { market, marketQuery } = useQuantMarket();
const capability = ref<QuantCapabilities | null>(null);
const regime = ref<MarketRegime | null>(null);
const history = ref<MarketRegime[]>([]);
const sectors = ref<SectorRegime[]>([]);
const ranking = ref<SignalRanking | null>(null);
const loading = ref(true);
const error = ref<ParsedApiError | null>(null);
let requestVersion = 0;

watch(
  market,
  async (current) => {
    const version = ++requestVersion;
    capability.value = null;
    regime.value = null;
    history.value = [];
    sectors.value = [];
    ranking.value = null;
    error.value = null;
    loading.value = true;
    const results = await Promise.allSettled([
      quantApi.capabilities(current),
      quantApi.marketRegime(current),
      quantApi.marketRegimeHistory(current),
      quantApi.sectors(current),
      quantApi.signals(current),
    ]);
    if (version !== requestVersion) return;
    if (results[0].status === 'fulfilled') capability.value = results[0].value;
    else error.value = getParsedApiError(results[0].reason);
    if (results[1].status === 'fulfilled') regime.value = results[1].value;
    if (results[2].status === 'fulfilled') history.value = results[2].value;
    if (results[3].status === 'fulfilled') sectors.value = results[3].value;
    if (results[4].status === 'fulfilled') ranking.value = results[4].value;
    loading.value = false;
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-5">
    <header>
      <h2 class="text-lg font-semibold">
        总览
      </h2>
      <p class="text-xs text-muted-foreground">
        展示市场状态、行业强弱、模型选股和组合建议。
      </p>
    </header>
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
            <CardDescription>市场状态</CardDescription><CardTitle class="text-2xl">
              {{ regime ? regimeLabels[regime.regime] : '数据不可用' }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>市场得分</CardDescription><CardTitle class="text-2xl">
              {{ formatScore(regime?.marketScore) }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>建议最大仓位</CardDescription><CardTitle class="text-2xl">
              {{ formatPercent(regime?.maxEquityExposure) }}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>模型 / 行情日期</CardDescription><CardTitle class="text-base">
              {{ ranking?.modelVersion ?? '—' }}
            </CardTitle><p class="text-xs text-muted-foreground">
              {{ ranking?.tradeDate ?? '—' }}
            </p>
          </CardHeader>
        </Card>
      </section>
      <Card>
        <CardHeader><CardTitle>市场得分历史</CardTitle><CardDescription>观察市场状态的时间序列变化。</CardDescription></CardHeader>
        <CardContent>
          <MarketScoreChart
            v-if="history.length"
            :items="history"
          /><Empty v-else>
            <EmptyHeader><EmptyTitle>暂无市场状态历史</EmptyTitle></EmptyHeader>
          </Empty>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>行业强弱</CardTitle><CardDescription>按相对收益与市场特征排序。</CardDescription></CardHeader>
        <CardContent>
          <div
            v-if="sectors.length"
          >
            <Table>
              <TableHeader><TableRow><TableHead>排名</TableHead><TableHead>行业</TableHead><TableHead>基准</TableHead><TableHead>得分</TableHead><TableHead>状态</TableHead><TableHead>5日相对收益</TableHead><TableHead>20日相对收益</TableHead></TableRow></TableHeader>
              <TableBody>
                <TableRow
                  v-for="item in sectors"
                  :key="item.sectorKey"
                >
                  <TableCell>{{ item.rank }}</TableCell><TableCell>{{ item.sectorKey }}</TableCell><TableCell>{{ item.benchmarkCode }}</TableCell><TableCell>{{ formatScore(item.sectorScore) }}</TableCell><TableCell>{{ item.state }}</TableCell><TableCell>{{ formatPercent(item.features.sectorRelativeMarket5d) }}</TableCell><TableCell>{{ formatPercent(item.features.sectorRelativeMarket20d) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
          <Empty v-else>
            <EmptyHeader><EmptyTitle>{{ market === 'CN' ? '暂无A股行业强弱数据' : '暂无行业强弱数据' }}</EmptyTitle><EmptyDescription>行业映射或当日行业计算尚未达到可用覆盖率。</EmptyDescription></EmptyHeader>
          </Empty>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>个股排名</CardTitle><CardDescription>生产模型生成的最新股票评分。</CardDescription><CardAction>
            <RouterLink
              :to="{ path: '/market/quant/signals', query: marketQuery() }"
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
            <table class="w-full text-sm">
              <thead class="text-left text-xs text-muted-foreground">
                <tr>
                  <th class="p-2">
                    排名
                  </th>
                  <th>股票</th>
                  <th>最终得分</th>
                  <th>横截面</th>
                  <th>时间序列</th>
                  <th>预测收益</th>
                  <th>信号</th>
                  <th>目标仓位</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in ranking.items.slice(0, 10)"
                  :key="item.id"
                  class="border-t border-border"
                >
                  <td class="p-2">
                    {{ item.universeRank ?? '—' }}
                  </td>
                  <td>
                    <RouterLink
                      :to="{ path: `/market/quant/signals/${item.code}`, query: marketQuery() }"
                      class="font-medium underline-offset-4 hover:underline"
                    >
                      {{ item.code }}
                    </RouterLink>
                  </td>
                  <td>{{ formatScore(item.finalScore) }}</td>
                  <td>{{ formatScore(item.crossSectionScore) }}</td>
                  <td>{{ formatScore(item.timeSeriesScore) }}</td>
                  <td>{{ formatPredictedReturn(item.predictedReturn) }}</td>
                  <td>{{ item.vetoed ? '否决' : item.signal }}</td>
                  <td>{{ formatPercent(item.targetPosition) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Empty
            v-else
            data-testid="quant-empty-state"
          >
            <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>{{ market === 'CN' ? '请先完成A股数据集构建、模型训练、人工发布和日频流水线。' : '生产模型、数据集或当日预测尚不可用。' }}</EmptyDescription></EmptyHeader>
          </Empty>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
