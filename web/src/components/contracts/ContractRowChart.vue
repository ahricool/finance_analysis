<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue';
import { contractsApi, type Candle, type ContractQuote } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { queueTableRequest } from '@/utils/tableRequests';
import ContractMarketPanel from './ContractMarketPanel.vue';

const props = defineProps<{ row: ContractQuote; period: '1d' | '1m' }>();
const bars = shallowRef<Candle[]>([]);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const retry = ref(0);
watch([() => props.row.symbol, () => props.period, retry], ([symbol, period], _, cleanup) => {
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
      if (parsed.status === 404) { bars.value = []; return; }
      error.value = parsed;
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
    :row="row"
    :interval="period"
    :bars="bars"
    :current="null"
    :loading="loading"
    :error="error"
    @retry="retry++"
  />
</template>
