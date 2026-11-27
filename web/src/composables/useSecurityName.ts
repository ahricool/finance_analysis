import { computed, inject, ref, watch, type MaybeRefOrGetter, toValue } from 'vue';
import { stocksApi } from '@/api/stocks';
import { rowVisibleKey } from '@/components/market-data/instrument-table/state';
import { queueTableRequest } from '@/utils/tableRequests';

const names = new Map<string, string>();
const pending = new Map<string, { promise: Promise<string>; request: AbortController; readers: number }>();

function lookup(key: string) {
  let entry = pending.get(key);
  if (!entry) {
    const request = new AbortController();
    const promise = queueTableRequest(request.signal, () => stocksApi.searchInstruments(key, { signal: request.signal })).then(items => {
      const match = items.find(item => item.code.toUpperCase() === key || item.nativeCode.toUpperCase() === key);
      const name = match?.name.trim() ?? '';
      if (name) names.set(key, name);
      return name;
    }).catch(() => '').finally(() => { if (pending.get(key)?.request === request) pending.delete(key); });
    entry = { promise, request, readers: 0 };
    pending.set(key, entry);
  }
  const current = entry;
  current.readers++;
  return {
    promise: current.promise,
    release() {
      if (--current.readers === 0 && pending.get(key) === current) {
        pending.delete(key);
        current.request.abort();
      }
    },
  };
}
export function useSecurityName(code: MaybeRefOrGetter<string | null | undefined>, name: MaybeRefOrGetter<string | null | undefined>) {
  const resolved = ref('');
  const visible = inject(rowVisibleKey, ref(true));
  watch(() => [toValue(code), toValue(name), visible.value] as const, async ([symbol, supplied, near], _, cleanup) => {
    const key = symbol?.trim().toUpperCase() ?? '';
    const label = supplied?.trim() ?? '';
    resolved.value = label && label.toUpperCase() !== key ? label : names.get(key) ?? '';
    if (!key || resolved.value || !near) return;
    const lookupRequest = lookup(key);
    let active = true;
    cleanup(() => { active = false; lookupRequest.release(); });
    const result = await lookupRequest.promise;
    if (active) resolved.value = result;
  }, { immediate: true });
  return computed(() => resolved.value || null);
}
