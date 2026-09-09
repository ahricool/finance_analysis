<script setup lang="ts">
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
import { formatPredictedReturn, formatScore } from '@/utils/quant';
import { formatSecurityLabel } from '@/utils/security';
import { computed, ref, watch } from 'vue';

const { market, marketQuery } = useQuantMarket();
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
  market,
  async (current) => {
    const version = ++requestVersion;
    ranking.value = null;
    error.value = null;
    loading.value = true;
    try {
      const value = await quantApi.signals(current);
      if (version === requestVersion) ranking.value = value;
    } catch (err) {
      if (version === requestVersion) error.value = getParsedApiError(err);
    } finally {
      if (version === requestVersion) loading.value = false;
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <header>
      <h2 class="text-lg font-semibold">
        模型选股排名
      </h2>
      <p class="text-xs text-muted-foreground">
        模型预测仅用于研究和生成目标组合，不代表真实订单。
        <span v-if="ranking?.modelVersion">当前版本：{{ ranking.modelVersion }}。</span>
      </p>
    </header>
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
        <CardHeader><CardTitle>筛选排名</CardTitle><CardDescription>按股票代码或名称缩小结果范围。</CardDescription></CardHeader><CardContent>
          <FieldInput
            v-model="filter"
            placeholder="股票代码或名称"
          />
        </CardContent>
      </Card>
      <Card
        v-if="items.length"
      >
        <CardHeader><CardTitle>模型排名</CardTitle><CardDescription>共 {{ items.length }} 个标的。</CardDescription></CardHeader>
        <CardContent class="block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>排名</TableHead><TableHead class="min-w-[220px]">
                  股票
                </TableHead><TableHead>最终得分</TableHead><TableHead>横截面</TableHead><TableHead>时间序列</TableHead><TableHead>风险扣分</TableHead><TableHead>预测收益</TableHead><TableHead>信号</TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="item in items"
                :key="item.id"
              >
                <TableCell>{{ item.universeRank ?? '—' }}</TableCell>
                <TableCell>
                  <RouterLink
                    :to="{ path: `/market/quant/signals/${item.code}`, query: marketQuery() }"
                    class="font-medium underline-offset-4 hover:underline"
                  >
                    {{ formatSecurityLabel(item.code, item.name) }}
                  </RouterLink>
                </TableCell><TableCell>{{ formatScore(item.finalScore) }}</TableCell><TableCell>{{ formatScore(item.crossSectionScore) }}</TableCell><TableCell>{{ formatScore(item.timeSeriesScore) }}</TableCell><TableCell>{{ formatScore(item.riskPenalty) }}</TableCell><TableCell>{{ formatPredictedReturn(item.predictedReturn) }}</TableCell><TableCell>
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
        <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>当前市场没有可展示的生产模型信号。</EmptyDescription></EmptyHeader>
      </Empty>
    </template>
  </div>
</template>
