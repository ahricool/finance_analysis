import { computed, reactive, ref, shallowRef, watch, type Ref } from 'vue';
import { useVirtualRows } from '@/composables/useVirtualRows';
import type { TrendRankingSnapshot } from '@/types/trendFollowing';
import { defaultBoxSort, mrPriority, type RankingColumn, type SortKey } from './rankingColumns';

// Each section owns its filters, ordering and scroll viewport. All share the same snapshot and drawer.
export type RankingTableKind = 'trend' | 'box' | 'mr';
export type RankingSortValue = (item: TrendRankingSnapshot, key: SortKey) => string | number | boolean | null;

export function createRankingTable(
  items: Ref<readonly TrendRankingSnapshot[]>,
  sortValue: RankingSortValue,
  kind: RankingTableKind, title: string, description: string, columns: readonly RankingColumn[],
) {
  const search = ref('');
  const filter = ref(kind === 'box' ? 'opportunities' : 'all');
  const sortKey = ref<SortKey>(kind === 'trend' ? 'rank' : kind === 'box' ? 'boxState' : 'mrState');
  const sortDirection = ref<'asc' | 'desc'>('asc');
  const viewport = shallowRef<HTMLElement | null>(null);
  const searchAll = computed(() => !!search.value.trim()
    && (kind === 'box' && filter.value === 'opportunities' || kind === 'mr' && filter.value === 'all'));
  const filteredItems = computed(() => {
    const query = search.value.trim().toLocaleLowerCase();
    return items.value.filter(item => {
      if (kind === 'box') {
        const state = item.features.boxState;
        if (!searchAll.value && (filter.value === 'opportunities' ? state !== 'BOX_BREAKOUT' && state !== 'BOX_READY' : state !== filter.value)) return false;
      } else if (kind === 'mr') {
        const state = item.features.mrState;
        if (!searchAll.value && (filter.value === 'all' ? state !== 'MR_REBOUND' && state !== 'MR_OVERSOLD' : state !== filter.value)) return false;
      } else if (filter.value !== 'all' && item.state !== filter.value) return false;
      return !query || item.code.toLocaleLowerCase().includes(query) || item.name.toLocaleLowerCase().includes(query);
    });
  });
  const sortedItems = computed(() => [...filteredItems.value].sort((left, right) => {
    const direction = sortDirection.value === 'asc' ? 1 : -1;
    if (kind === 'mr' && sortKey.value === 'mrState') return (mrPriority(left) - mrPriority(right)
      || (right.features.mrQuality ?? -1) - (left.features.mrQuality ?? -1) || left.code.localeCompare(right.code)) * direction;
    if (kind === 'box' && sortKey.value === 'boxState') return defaultBoxSort(left, right) * direction;
    const a = sortValue(left, sortKey.value), b = sortValue(right, sortKey.value);
    if (a == null) return b == null ? left.code.localeCompare(right.code) : 1;
    if (b == null) return -1;
    const comparison = typeof a !== 'string' && typeof b !== 'string' ? Number(a) - Number(b) : String(a).localeCompare(String(b));
    return comparison * direction || left.code.localeCompare(right.code);
  }));
  const { scrollTop, virtual, range, rows: renderedRows, rowHeight } = useVirtualRows(sortedItems);
  watch(sortedItems, () => { scrollTop.value = 0; if (viewport.value) viewport.value.scrollTop = 0; });
  function toggleSort(key: SortKey) {
    sortDirection.value = sortKey.value === key ? sortDirection.value === 'asc' ? 'desc' : 'asc'
      : ['rank', 'name', 'setup', 'state', 'trendCandidate', 'priorCompression', 'compressionBreakout', 'trendResume'].includes(key) ? 'asc' : 'desc';
    sortKey.value = key;
  }
  return reactive({ kind, title, description, columns, exporting: false, search, filter, sortKey, sortDirection, viewport, scrollTop,
    searchAll, sortedItems, virtual, range, renderedRows, rowHeight, toggleSort,
    groups: [...new Set(columns.map(c => c.group))].map(label => ({ label, count: columns.filter(c => c.group === label).length })),
  });
}
