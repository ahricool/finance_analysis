import { computed, ref } from 'vue';

/** Local table ordering. Missing values stay last in both directions. */
export function useQuantTableSort<T>(rows: () => T[], value: (row: T, key: string) => unknown, initialKey: string, initialDirection: 'asc' | 'desc' = 'asc') {
  const sortKey = ref(initialKey);
  const direction = ref<'asc' | 'desc'>(initialDirection);
  function toggle(key: string) {
    direction.value = sortKey.value === key && direction.value === 'asc' ? 'desc' : 'asc';
    sortKey.value = key;
  }
  const sorted = computed(() => !sortKey.value ? rows() : rows().map((row, index) => ({ row, index })).sort((a, b) => {
    const left = value(a.row, sortKey.value), right = value(b.row, sortKey.value);
    const missing = (x: unknown) => x == null || x === '' || (typeof x === 'number' && !Number.isFinite(x));
    if (missing(left) || missing(right)) return Number(missing(left)) - Number(missing(right)) || a.index - b.index;
    const comparison = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), 'zh-CN', { numeric: true });
    return (direction.value === 'asc' ? comparison : -comparison) || a.index - b.index;
  }).map(x => x.row));
  return { sortKey, direction, toggle, sorted };
}
