import { ref, shallowRef, watch, type Ref } from 'vue';
import { marketDataApi, type ForwardReturnItem } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';

export const forwardReturnColumns = [3, 5, 10].map(days => ({
  key: `forwardReturn${days}D` as 'forwardReturn3D' | 'forwardReturn5D' | 'forwardReturn10D',
  label: `未来 ${days}D`, group: 'Core', format: 'percent' as const,
  description: `所选日收盘至未来第 ${days} 个交易日收盘的前复权收益率；未到期或行情缺失显示 —。`,
}));

export function useForwardReturns(
  items: Ref<{ code: string }[]>, market: Ref<string>, tradeDate: () => string, mode: Ref<string>,
) {
  const values = shallowRef<Record<string, ForwardReturnItem>>({});
  const error = ref<ParsedApiError | null>(null);
  const loading = ref(false);
  const revision = ref(0);
  watch([items, market, tradeDate, mode, revision], async (_, __, onCleanup) => {
    const request = new AbortController();
    onCleanup(() => request.abort());
    values.value = {};
    error.value = null;
    loading.value = false;
    if (mode.value !== 'official' || !tradeDate() || !items.value.length) return;
    loading.value = true;
    try {
      const response = await marketDataApi.forwardReturns(items.value.map(row => row.code), market.value, tradeDate(), request.signal);
      if (!request.signal.aborted) values.value = Object.fromEntries(response.items.map(row => [row.code, row]));
    } catch (e) {
      if (!request.signal.aborted) error.value = getParsedApiError(e);
    } finally {
      if (!request.signal.aborted) loading.value = false;
    }
  }, { immediate: true });
  function value(code: string, key: string): number | null {
    return values.value[code]?.[key as keyof Omit<ForwardReturnItem, 'code'>] ?? null;
  }
  return { value, error, loading, retry: () => { revision.value++; } };
}
