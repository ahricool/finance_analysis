<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { RefreshCw } from 'lucide-vue-next';
import { getMarketHeatmap, type HeatmapMarket, type HeatmapResponse, type HeatmapStock } from '@/api/marketHeatmap';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import HeatmapChart from '@/components/market-heatmap/HeatmapChart.vue';
import { colorScale, formatCap } from '@/components/market-heatmap/display';
import { useStockDetail } from '@/composables/useStockDetail';
import StockDetailHost from '@/components/stocks/StockDetailHost.vue';
import { formatDateTime } from '@/utils/format';
const route = useRoute();
const router = useRouter();
const market = computed<HeatmapMarket>(() => route.query.market === 'US' ? 'US' : 'CN');
const result = shallowRef<HeatmapResponse | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false);
const chartVersion = ref(0);
const detail = useStockDetail();
let sequence = 0;
const snapshot = computed(() => result.value?.snapshot);
async function load() {
  const request = ++sequence;
  loading.value = true; error.value = null;
  try { const data = await getMarketHeatmap(market.value); if (request === sequence) result.value = data; }
  catch (cause) { if (request === sequence) error.value = getParsedApiError(cause); }
  finally { if (request === sequence) loading.value = false; }
}
watch(market, () => { sequence++; result.value = null; chartVersion.value++; void load(); }, { immediate: true });
const timer = setInterval(() => { void load(); }, 15 * 60 * 1000);
onBeforeUnmount(() => { sequence++; clearInterval(timer); });
function select(stock: HeatmapStock) {
  detail.open({ code: stock.code, name: stock.name, market_type: market.value });
}
function switchMarket(value: HeatmapMarket) { void router.replace({ query: { ...route.query, market: value } }); }
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="market-heatmap-page"
  >
    <PageHeader
      title="热力图"
      en="Market Heatmap"
      variant="section"
      description="按行业观察市场涨跌，方块越大代表相对市值越高。"
    >
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <div
            class="flex rounded-lg border p-1"
            aria-label="热力图市场"
          >
            <Button
              v-for="value in (['CN', 'US'] as const)"
              :key="value"
              size="sm"
              :variant="market === value ? 'default' : 'ghost'"
              :aria-pressed="market === value"
              :data-testid="`heatmap-market-${value}`"
              @click="switchMarket(value)"
            >
              {{ value === 'CN' ? 'A 股' : '美股' }}
            </Button>
          </div>
          <Button
            variant="outline"
            size="sm"
            :disabled="loading"
            aria-label="重新读取热力图快照"
            @click="load"
          >
            <RefreshCw
              class="mr-1 size-3.5"
              :class="{ 'animate-spin': loading }"
            />重新加载
          </Button>
          <Button
            variant="ghost"
            size="sm"
            @click="chartVersion++"
          >
            全景
          </Button>
        </div>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重新加载"
      @action="load"
      @dismiss="error = null"
    />
    <Skeleton
      v-if="loading && !snapshot"
      class="h-[65vh] min-h-96"
    />
    <template v-if="snapshot">
      <div class="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-xs text-muted-foreground">
        <p><span class="font-medium text-foreground">{{ snapshot.items.length.toLocaleString() }} 只股票</span> · 总市值 ≥ {{ formatCap(snapshot.minMarketCap, market) }} · 每15分钟更新</p>
        <p>行情时间 {{ formatDateTime(snapshot.dataLatestAt) }} · 快照 {{ formatDateTime(snapshot.generatedAt) }}</p>
      </div>
      <p
        v-if="result?.status === 'stale'"
        class="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm"
        role="status"
      >
        最新刷新已延迟，当前显示上次成功快照。
      </p>
      <div
        class="h-[72vh] min-h-[28rem] max-h-[64rem] overflow-hidden rounded-lg border p-1"
        data-testid="heatmap-chart"
      >
        <HeatmapChart
          :key="`${market}-${chartVersion}`"
          :snapshot="snapshot"
          @select="select"
        />
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <div
          class="flex items-center gap-1"
          aria-label="涨跌幅色标：绿跌红涨"
        >
          <span
            v-for="step in colorScale"
            :key="step.label"
            class="px-2 py-1 text-white"
            :style="{ backgroundColor: step.color }"
          >{{ step.label }}</span>
        </div>
        <p>点击行业放大 · 点击股票查看详情 · 灰色表示涨跌幅暂缺</p>
      </div>
      <p class="text-xs leading-relaxed text-muted-foreground">
        面积经过压缩，单只股票在全景中的占比最多约3%；悬浮查看真实市值。数据源：{{ market === 'CN' ? '腾讯行情' : 'Yahoo Finance' }}。
        {{ snapshot.unclassifiedCount ? `${snapshot.unclassifiedCount} 只股票暂未分类。` : '' }}行业观测：{{ formatDateTime(snapshot.classificationObservedAt) }}。
      </p>
    </template>
    <div
      v-else-if="!loading && !error"
      class="flex min-h-96 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-muted-foreground"
      role="status"
    >
      <p class="text-base font-medium text-foreground">
        尚无热力图快照
      </p><p class="px-4 text-center text-sm">
        后台每15分钟刷新一次，首份快照生成后会在这里显示。
      </p>
    </div>
    <StockDetailHost />
  </div>
</template>
