import { reactive } from 'vue';
import { useQuantTableSort } from './useQuantTableSort';

/** Sort source data before pagination; an empty key preserves the business order. */
export function useTableSort<T>(rows: () => T[], value: (row: T, key: string) => unknown) {
  const sort = useQuantTableSort(rows, value, '');
  return reactive({
    ...sort,
    header(key: string) {
      return {
        active: sort.sortKey.value === key,
        direction: sort.direction.value,
        onSort: () => sort.toggle(key),
      };
    },
  });
}

/** Decimal API strings must sort numerically while preserving missing values. */
export function sortNumber(value: unknown): number | null {
  if (value == null || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function sortTime(value: string | null | undefined): number | null {
  return value ? sortNumber(Date.parse(value)) : null;
}

/** Read raw nested fields, never the rounded/formatted text displayed in cells. */
export function sortField(row: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((value, key) =>
    value !== null && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined, row);
}

/** Repeated evidence groups each keep their own header selection and direction. */
export function useGroupedTableSort<T>(rows: (group: string) => T[], value: (row: T, key: string) => unknown) {
  const tables = new Map<string, ReturnType<typeof useTableSort<T>>>();
  return (group: string) => {
    let table = tables.get(group);
    if (!table) {
      table = useTableSort(() => rows(group), value);
      tables.set(group, table);
    }
    return table;
  };
}
