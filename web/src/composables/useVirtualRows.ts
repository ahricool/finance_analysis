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
export function useVirtualRows<T>(items: MaybeRefOrGetter<readonly T[]>, options: VirtualRowsOptions = {}) {
  const rowHeight = options.rowHeight ?? 64;
  const threshold = options.threshold ?? 300;
  const scrollTop = ref(0);
  const virtual = computed(() => toValue(items).length > threshold);
  const range = computed<VirtualWindow>(() => {
    const total = toValue(items).length;
    return virtual.value ? virtualWindow(total, scrollTop.value, options) : { start: 0, end: total, topSpace: 0, bottomSpace: 0 };
  });
  const rows = computed(() => toValue(items).slice(range.value.start, range.value.end));
  return { scrollTop, virtual, range, rows, rowHeight };
}
