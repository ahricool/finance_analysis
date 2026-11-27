import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue';

export type VirtualRowsOptions = {
  /** Fixed row height in px; rendered rows must be pinned to it while virtual. */
  rowHeight?: number;
  /** Rows kept in the DOM at once. */
  windowSize?: number;
  /** Rows rendered above the first visible row so fast scrolls do not flash empty. */
  overscan?: number;
  /** Height of the sticky header above the first body row. */
  headerOffset?: number;
  /** Only virtualize past this many rows; small tables render everything. */
  threshold?: number;
};

export type VirtualWindow = { start: number; end: number; topSpace: number; bottomSpace: number };

/** Pure windowing math for a fixed-row-height table body with spacer rows. */
export function virtualWindow(total: number, scrollTop: number, {
  rowHeight = 64, windowSize = 28, overscan = 8, headerOffset = 80,
}: VirtualRowsOptions = {}): VirtualWindow {
  const firstVisible = Math.floor(Math.max(0, scrollTop - headerOffset) / rowHeight);
  const start = Math.min(Math.max(0, total - windowSize), Math.max(0, firstVisible - overscan));
  const end = Math.min(total, start + windowSize);
  return { start, end, topSpace: start * rowHeight, bottomSpace: (total - end) * rowHeight };
}

/**
 * Keeps table semantics (spacer <tr>s around real rows) instead of a wrapper list,
 * so sticky headers, aria-rowindex and column widths keep working.
 */
export function useVirtualRows<T>(items: MaybeRefOrGetter<readonly T[]>, options: VirtualRowsOptions = {}, extraHeight?: (item: T) => number) {
  const rowHeight = options.rowHeight ?? 64;
  const threshold = options.threshold ?? 300;
  const scrollTop = ref(0);
  const virtual = computed(() => toValue(items).length > threshold);
  const offsets = computed(() => {
    if (!virtual.value || !extraHeight) return null;
    const ends = [0];
    for (const item of toValue(items)) ends.push(ends[ends.length - 1]! + rowHeight + extraHeight(item));
    return ends;
  });
  const range = computed<VirtualWindow>(() => {
    const total = toValue(items).length;
    const ends = offsets.value;
    if (ends) {
      const top = Math.max(0, scrollTop.value - (options.headerOffset ?? 80));
      let low = 0;
      let high = total;
      while (low < high) {
        const mid = Math.floor((low + high) / 2);
        if (ends[mid + 1]! <= top) low = mid + 1;
        else high = mid;
      }
      const size = options.windowSize ?? 28;
      const start = Math.max(0, Math.min(total - size, low - (options.overscan ?? 8)));
      const end = Math.min(total, start + size);
      return { start, end, topSpace: ends[start]!, bottomSpace: ends[total]! - ends[end]! };
    }
    return virtual.value ? virtualWindow(total, scrollTop.value, options) : { start: 0, end: total, topSpace: 0, bottomSpace: 0 };
  });
  const rows = computed(() => toValue(items).slice(range.value.start, range.value.end));
  return { scrollTop, virtual, range, rows, rowHeight };
}
