import { computed, onBeforeUnmount, ref } from 'vue';
import { dragonTigerFlowApi, type FlowFilters, type FlowOverview } from '@/api/dragonTigerFlow';
import { getParsedApiError } from '@/api/error';
import { conceptStocks, stockEvidence } from '@/components/dragon-tiger-flow/display';

export function useDragonTigerFlow() {
  const filters = ref<FlowFilters>({ endDate: '', days: 20, board: 'all', rangeDays: 1 });
  const data = ref<FlowOverview | null>(null);
  const dates = ref<string[]>([]);
  const error = ref<ReturnType<typeof getParsedApiError> | null>(null);
  const datesError = ref<ReturnType<typeof getParsedApiError> | null>(null);
  const loading = ref(false), selected = ref(''), stock = ref('');
  let generation = 0, disposed = false;
  onBeforeUnmount(() => { disposed = true; generation++; });
  const concept = computed(() => data.value?.concepts.find(c => c.id === selected.value));
  const stocks = computed(() => conceptStocks(data.value, selected.value));
  const stockRows = computed(() => stockEvidence(data.value, stock.value));
  async function loadDates() {
    datesError.value = null;
    try { const result = await dragonTigerFlowApi.dates(); if (!disposed) dates.value = result.map(d => d.tradeDate); }
    catch (e) { if (!disposed) datesError.value = getParsedApiError(e); }
  }
  async function load() {
    const current = ++generation;
    loading.value = true; error.value = null; data.value = null; stock.value = '';
    try {
      const result = await dragonTigerFlowApi.overview({ ...filters.value });
      if (disposed || current !== generation) return;
      data.value = result;
      if (!result.concepts.some(c => c.id === selected.value)) selected.value = result.concepts[0]?.id ?? '';
    } catch (e) { if (!disposed && current === generation) error.value = getParsedApiError(e); }
    finally { if (!disposed && current === generation) loading.value = false; }
  }
  function change(patch: Partial<FlowFilters>) { filters.value = { ...filters.value, ...patch }; void load(); }
  return { filters, data, dates, error, datesError, loading, selected, stock, concept, stocks, stockRows, load, loadDates, change };
}
