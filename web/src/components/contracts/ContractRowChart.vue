<script setup lang="ts">
import { getDisplayTimezone } from '@/utils/format';
import { computed, ref, shallowRef, watch } from 'vue';
import { contractsApi, type Candle, type ContractQuote } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { queueTableRequest } from '@/utils/tableRequests';
import ContractMarketPanel from './ContractMarketPanel.vue';

import { aggregateContracts, nativeInterval } from './periods';
import type { ChartPeriod } from '@/components/market-data/instrument-table/state';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import TableExpansionPanel from '@/components/market-data/TableExpansionPanel.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';

const props = defineProps<{ row: ContractQuote; period: ChartPeriod }>();
const bars = shallowRef<Candle[]>([]);
const interval = computed(() => nativeInterval(props.period));
const aggregated = computed(() => aggregateContracts(bars.value, props.period, Date.now()));
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const retry = ref(0);
watch([() => props.row.symbol, interval, retry], ([symbol, period], _, cleanup) => {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  bars.value = [];
  loading.value = true;
  error.value = null;
  cleanup(() => { controller.abort(); clearTimeout(timer); });
  async function refresh() {
    try {
      const data = await queueTableRequest(controller.signal, () => contractsApi.bars(symbol, controller.signal, period, true));
      if (!controller.signal.aborted) { bars.value = data; error.value = null; }
    } catch (reason) {
      if (controller.signal.aborted) return;
      const parsed = getParsedApiError(reason);
      if (parsed.status === 404) bars.value = [];
      else error.value = parsed;
    } finally {
      if (!controller.signal.aborted) loading.value = false;
    }
    if (!controller.signal.aborted) timer = setTimeout(refresh, period === '1m' ? 5000 : 60000);
  }
  void refresh();
}, { immediate: true });
</script>

<template>
  <ContractMarketPanel
    v-if="period === '1m' || period === '1d'"
    :row="row"
    :interval="period"
    :bars="bars"
    :current="null"
    :loading="loading"
    :error="error"
    @retry="retry++"
  />
  <TableExpansionPanel v-else>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="retry++"
    />
    <MarketKLineChart
      v-else-if="aggregated.bars.length || aggregated.current"
      :symbol="row.symbol"
      :period="period"
      :bars="aggregated.bars"
      :current="aggregated.current"
      :timezone="interval === '1m' ? getDisplayTimezone() : undefined"
      live-snapshot
      disable-forecast
    />
    <p
      v-else
      class="p-6 text-sm text-muted-foreground"
    >
      {{ loading ? '行情加载中…' : '无数据 · 周期内 K 线不足' }}
    </p>
  </TableExpansionPanel>
</template>
