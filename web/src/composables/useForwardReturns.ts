import { computed, ref, shallowRef, watch, type Ref } from 'vue';
import { marketDataApi, type ForwardReturnItem } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';

export const forwardReturnColumns = [3, 5, 10, 20].map(days => ({
  key: `forwardReturn${days}D` as 'forwardReturn3D' | 'forwardReturn5D' | 'forwardReturn10D' | 'forwardReturn20D',
  label: `未来 ${days}D`, group: 'Core', format: 'percent' as const,
  description: `所选日收盘至未来第 ${days} 个交易日收盘的前复权收益率；未到期或行情缺失显示 —。T 收盘基准仅用于事后研究，不代表可以按该价格成交。`,
}));

export function useForwardReturns(
  items: Ref<{ code: string }[]>, market: Ref<string>, tradeDate: () => string, mode: Ref<string>,
  wholeTable: () => boolean,
) {
  const values = shallowRef<Record<string, ForwardReturnItem | null>>({});
  const error = ref<ParsedApiError | null>(null);
  const loading = ref(false);
  const revision = ref(0);
  const visible = ref(new Map<string, number>());
  function visibility(code: string, near: boolean) {
    const count = (visible.value.get(code) ?? 0) + (near ? 1 : -1);
    if (count > 0) visible.value.set(code, count);
    else visible.value.delete(code);
  }

  let context: AbortController;
  watch([items, market, tradeDate, mode], (_, __, cleanup) => {
    context = new AbortController();
    cleanup(() => context.abort());
    values.value = {};
    error.value = null;
    revision.value++;
  }, { immediate: true, flush: 'sync' });

  async function fetchMissing(codes: string[], signal: AbortSignal) {
    if (mode.value !== 'official' || !tradeDate()) return;
    const missing = codes.filter(code => !(code in values.value));
    for (let i = 0; i < missing.length; i += 50) {
      signal.throwIfAborted();
      const batch = missing.slice(i, i + 50);
      const response = await marketDataApi.forwardReturns(batch, market.value, tradeDate(), signal);
      signal.throwIfAborted();
      const result = new Map(response.items.map(row => [row.code, row]));
      values.value = { ...values.value, ...Object.fromEntries(batch.map(code => [code, result.get(code) ?? null])) };
    }
  }
  const wanted = computed(() => wholeTable() ? items.value.map(row => row.code) : [...visible.value.keys()]);
  watch([wanted, revision], async ([codes], _, cleanup) => {
    const request = new AbortController();
    const signal = AbortSignal.any([context.signal, request.signal]);
    cleanup(() => request.abort());
    error.value = null;
    loading.value = mode.value === 'official' && !!tradeDate() && codes.some(code => !(code in values.value));
    try {
      await fetchMissing(codes, signal);
    } catch (e) {
      if (!signal.aborted) error.value = getParsedApiError(e);
    } finally {
      if (!signal.aborted) loading.value = false;
    }
  }, { immediate: true });
  function value(code: string, key: string): number | null {
    return values.value[code]?.[key as keyof Omit<ForwardReturnItem, 'code'>] ?? null;
  }
  return {
    value, error, loading, visibility, retry: () => { revision.value++; },
    forExport: (rows: readonly { code: string }[]) => fetchMissing(rows.map(row => row.code), context.signal),
  };
}
