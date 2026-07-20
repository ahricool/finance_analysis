<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import MarketScoreChart from '@/components/quant/MarketScoreChart.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { MarketRegime, QuantCapabilities, SectorRegime, SignalRanking } from '@/types/quant';
import { formatPercent, formatPredictedReturn, formatScore, regimeLabels } from '@/utils/quant';
import { Activity } from 'lucide-vue-next';
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

watch(market, async (current) => {
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
}, { immediate: true });
</script>

<template>
  <div class="space-y-5">
    <header class="flex items-start gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-primary-foreground">
        <Activity class="h-5 w-5" />
      </div>
      <div>
        <h2 class="text-lg font-semibold">
          量化研究
        </h2><p class="text-xs text-secondary-text">
          展示市场状态、行业强弱、模型选股和组合建议。
        </p>
      </div>
    </header>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="capability?.warnings.length"
      class="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning"
      data-testid="raw-price-warning"
    >
      {{ capability.warnings.join('；') }}
    </div>
    <div
      v-if="loading"
      class="py-12 text-center text-muted-text"
    >
      加载中...
    </div>
    <template v-else>
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-2xl border border-border bg-card p-4">
          <p class="text-xs text-muted-text">
            市场状态
          </p><p class="mt-2 text-xl font-semibold">
            {{ regime ? regimeLabels[regime.regime] : '数据不可用' }}
          </p>
        </div>
        <div class="rounded-2xl border border-border bg-card p-4">
          <p class="text-xs text-muted-text">
            市场得分
          </p><p class="mt-2 text-xl font-semibold">
            {{ formatScore(regime?.marketScore) }}
          </p>
        </div>
        <div class="rounded-2xl border border-border bg-card p-4">
          <p class="text-xs text-muted-text">
            建议最大仓位
          </p><p class="mt-2 text-xl font-semibold">
            {{ formatPercent(regime?.maxEquityExposure) }}
          </p>
        </div>
        <div class="rounded-2xl border border-border bg-card p-4">
          <p class="text-xs text-muted-text">
            模型 / 行情日期
          </p><p class="mt-2 text-sm font-medium">
            {{ regime?.modelVersion ?? '—' }}
          </p><p class="text-xs text-muted-text">
            {{ ranking?.tradeDate ?? '—' }}
          </p>
        </div>
      </section>
      <section class="rounded-2xl border border-border bg-card p-4">
        <h3 class="text-sm font-semibold">
          市场得分历史
        </h3><MarketScoreChart
          v-if="history.length"
          :items="history"
        /><EmptyState
          v-else
          title="暂无市场状态历史"
        />
      </section>
      <section class="rounded-2xl border border-border bg-card p-4">
        <h3 class="mb-3 text-sm font-semibold">
          行业强弱
        </h3>
        <div
          v-if="sectors.length"
          class="overflow-x-auto"
        >
          <table class="w-full text-sm">
            <thead class="text-left text-xs text-muted-text">
              <tr>
                <th class="p-2">
                  排名
                </th><th>行业</th><th>基准</th><th>得分</th><th>状态</th><th>5日相对收益</th><th>20日相对收益</th>
              </tr>
            </thead><tbody>
              <tr
                v-for="item in sectors"
                :key="item.sectorKey"
                class="border-t border-border"
              >
                <td class="p-2">
                  {{ item.rank }}
                </td><td>{{ item.sectorKey }}</td><td>{{ item.benchmarkCode }}</td><td>{{ formatScore(item.sectorScore) }}</td><td>{{ item.state }}</td><td>{{ formatPercent(item.features.sectorRelativeMarket5d) }}</td><td>{{ formatPercent(item.features.sectorRelativeMarket20d) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState
          v-else
          :title="market === 'CN' ? '暂无A股行业强弱数据' : '暂无行业强弱数据'"
          description="行业映射或当日行业计算尚未达到可用覆盖率。"
        />
      </section>
      <section class="rounded-2xl border border-border bg-card p-4">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-sm font-semibold">
            个股排名
          </h3><RouterLink
            :to="{ path: '/market/quant/signals', query: marketQuery() }"
            class="text-xs text-primary"
          >
            查看全部
          </RouterLink>
        </div>
        <div
          v-if="ranking?.items.length"
          class="overflow-x-auto"
        >
          <table class="w-full text-sm">
            <thead class="text-left text-xs text-muted-text">
              <tr>
                <th class="p-2">
                  排名
                </th><th>股票</th><th>最终得分</th><th>横截面</th><th>时间序列</th><th>事件</th><th>预测收益</th><th>信号</th><th>目标仓位</th>
              </tr>
            </thead><tbody>
              <tr
                v-for="item in ranking.items.slice(0, 10)"
                :key="item.id"
                class="border-t border-border"
              >
                <td class="p-2">
                  {{ item.universeRank ?? '—' }}
                </td><td>
                  <RouterLink
                    :to="{ path: `/market/quant/signals/${item.code}`, query: marketQuery() }"
                    class="font-medium text-primary"
                  >
                    {{ item.code }}
                  </RouterLink>
                </td><td>{{ formatScore(item.finalScore) }}</td><td>{{ formatScore(item.crossSectionScore) }}</td><td>{{ formatScore(item.timeSeriesScore) }}</td><td>{{ formatScore(item.eventScore) }}</td><td>{{ formatPredictedReturn(item.predictedReturn) }}</td><td>{{ item.vetoed ? '否决' : item.signal }}</td><td>{{ formatPercent(item.targetPosition) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState
          v-else
          :title="market === 'CN' ? 'A股模型尚未就绪' : '暂无模型排名'"
          :description="market === 'CN' ? '请先完成A股数据集构建、模型训练、人工发布和日频流水线。' : '生产模型、数据集或当日预测尚不可用。'"
          data-testid="quant-empty-state"
        />
      </section>
    </template>
  </div>
</template>
