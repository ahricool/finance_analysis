<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { SignalRanking } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore } from '@/utils/quant';
import { computed, ref, watch } from 'vue';

const { market, marketQuery } = useQuantMarket();
const ranking = ref<SignalRanking | null>(null);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const filter = ref('');
const vetoed = ref('all');
const items = computed(
  () =>
    ranking.value?.items.filter(
      (item) =>
        (!filter.value || item.code.includes(filter.value.toUpperCase())) &&
        (vetoed.value === 'all' || String(item.vetoed) === vetoed.value),
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
        模型预测仅用于研究和组合建议，不代表真实订单。
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
        <CardHeader><CardTitle>筛选排名</CardTitle><CardDescription>按股票代码和风控否决状态缩小结果范围。</CardDescription></CardHeader><CardContent class="grid gap-3 sm:grid-cols-2">
          <FieldInput
            v-model="filter"
            placeholder="股票代码"
          />
          <FieldSelect
            v-model="vetoed"
            :options="[
              { value: 'all', label: '全部' },
              { value: 'true', label: '已否决' },
              { value: 'false', label: '未否决' },
            ]"
          />
        </CardContent>
      </Card>
      <Card
        v-if="items.length"
      >
        <CardHeader><CardTitle>模型排名</CardTitle><CardDescription>共 {{ items.length }} 个标的。</CardDescription></CardHeader>
        <CardContent class="hidden md:block">
          <Table>
            <TableHeader><TableRow><TableHead>排名</TableHead><TableHead>股票</TableHead><TableHead>最终/原始</TableHead><TableHead>横截面</TableHead><TableHead>时间序列</TableHead><TableHead>预测收益</TableHead><TableHead>目标仓位</TableHead><TableHead>信号</TableHead></TableRow></TableHeader><TableBody>
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
                    {{ item.code }}
                  </RouterLink>
                </TableCell><TableCell>{{ formatScore(item.finalScore) }} / {{ formatScore(item.rawFinalScore) }}</TableCell><TableCell>{{ formatScore(item.crossSectionScore) }}</TableCell><TableCell>{{ formatScore(item.timeSeriesScore) }}</TableCell><TableCell>{{ formatPredictedReturn(item.predictedReturn) }}</TableCell><TableCell>{{ formatPercent(item.targetPosition) }}</TableCell><TableCell>
                  <Badge :variant="item.vetoed ? 'destructive' : 'outline'">
                    {{ item.vetoed ? '已否决' : item.signal }}
                  </Badge>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
        <CardContent class="space-y-3 md:hidden">
          <Card
            v-for="item in items"
            :key="item.id"
          >
            <CardHeader>
              <CardTitle class="text-base">
                <RouterLink
                  :to="{ path: `/market/quant/signals/${item.code}`, query: marketQuery() }"
                  class="font-medium underline-offset-4 hover:underline"
                >
                  {{ item.code }}
                </RouterLink>
              </CardTitle><CardDescription>排名 #{{ item.universeRank ?? '—' }}</CardDescription><Badge :variant="item.vetoed ? 'destructive' : 'outline'">
                {{ item.vetoed ? '已否决' : item.signal }}
              </Badge>
            </CardHeader><CardContent class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p class="text-xs text-muted-foreground">
                  最终得分
                </p>{{ formatScore(item.finalScore) }}
              </div><div>
                <p class="text-xs text-muted-foreground">
                  目标仓位
                </p>{{ formatPercent(item.targetPosition) }}
              </div>
            </CardContent>
          </Card>
        </CardContent>
      </Card>
      <Empty v-else>
        <EmptyHeader><EmptyTitle>{{ market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名' }}</EmptyTitle><EmptyDescription>当前市场没有可展示的生产模型信号。</EmptyDescription></EmptyHeader>
      </Empty>
    </template>
  </div>
</template>
