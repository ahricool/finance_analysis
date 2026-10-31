import { computed, onScopeDispose, ref, watch, type MaybeRefOrGetter, toValue } from 'vue';
import { stocksApi } from '@/api/stocks';

// Share exact master-data lookups for symbol-only event entries.
const names = new Map<string, string>();
const pending = new Map<string, Promise<string>>();
function lookup(code: string): Promise<string> {
  const key = code.trim().toUpperCase();
  if (names.has(key)) return Promise.resolve(names.get(key)!);
  if (pending.has(key)) return pending.get(key)!;
  const request = Promise.resolve().then(() => stocksApi.searchInstruments(key)).then(items => {
    const match = items.find(item => item.code.toUpperCase() === key || item.nativeCode.toUpperCase() === key);
    const name = match?.name.trim() ?? '';
    if (name) names.set(key, name);
    return name;
  }).catch(() => '').finally(() => { pending.delete(key); });
  pending.set(key, request);
  return request;
}
export function useSecurityName(code: MaybeRefOrGetter<string | null | undefined>, name: MaybeRefOrGetter<string | null | undefined>) {
  const resolved = ref('');
  let generation = 0;
  watch(() => [toValue(code), toValue(name)] as const, async ([symbol, supplied]) => {
    const current = ++generation;
    resolved.value = '';
    const key = symbol?.trim() ?? '';
    const label = supplied?.trim() ?? '';
    if (label && label.toUpperCase() !== key.toUpperCase()) { resolved.value = label; return; }
    if (!key) return;
    const result = await lookup(key);
    if (current === generation) resolved.value = result;
  }, { immediate: true });
  onScopeDispose(() => { generation++; });
  return computed(() => resolved.value || null);
}
