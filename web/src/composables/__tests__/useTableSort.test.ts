import { describe, expect, it } from 'vitest';
import { ref } from 'vue';
import { useGroupedTableSort, useTableSort, sortField, sortNumber, sortTime } from '../useTableSort';

describe('shared local table sorting', () => {
  it('preserves business order until a header is clicked, sorts before slicing and leaves missing data last', () => {
    const rows = ref(Array.from({ length: 20 }, (_, index) => ({ id: index, score: index === 1 ? null : 20 - index })));
    const original = rows.value.map(row => row.id);
    const table = useTableSort(() => rows.value, sortField);
    expect(table.sorted.map(row => row.id)).toEqual(original);
    expect(table.header('score').active).toBe(false);
    table.header('score').onSort();
    expect(table.sorted.slice(0, 15)[0]?.id).toBe(19);
    expect(table.sorted.at(-1)?.id).toBe(1);
    expect(table.header('score')).toMatchObject({ active: true, direction: 'asc' });
    table.header('score').onSort();
    expect(table.sorted[0]?.id).toBe(0);
    expect(table.sorted.at(-1)?.id).toBe(1);
    expect(rows.value.map(row => row.id)).toEqual(original);
    rows.value[19]!.score = 100;
    expect(table.sorted[0]?.id).toBe(19);
  });

  it('compares decimal API values numerically, keeps equal rows stable, and preserves null and invalid values', () => {
    const rows = [{ id: 1, value: '10' }, { id: 2, value: '2' }, { id: 3, value: null },
      { id: 4, value: '-0.2' }, { id: 5, value: '2' }, { id: 6, value: 'bad' }];
    const table = useTableSort(() => rows, row => sortNumber(row.value));
    table.toggle('value');
    expect(table.sorted.map(row => row.id)).toEqual([4, 2, 5, 1, 3, 6]);
    table.toggle('value');
    expect(table.sorted.map(row => row.id)).toEqual([1, 2, 5, 4, 3, 6]);
    expect(sortNumber('')).toBeNull();
    expect(sortTime('invalid')).toBeNull();
    expect(sortTime('2026-10-30T10:00:00-04:00')).toBe(sortTime('2026-10-30T14:00:00Z'));
  });

  it('maintains independent sort state per evidence group and reads raw nested values', () => {
    const groups = ref({ a: [{ nested: { value: 2 } }, { nested: { value: 1 } }], b: [{ nested: { value: 4 } }, { nested: { value: 3 } }] });
    const tables = useGroupedTableSort(key => groups.value[key as 'a' | 'b'], sortField);
    tables('a').toggle('nested.value');
    expect(tables('a').sorted.map(row => row.nested.value)).toEqual([1, 2]);
    expect(tables('b').sorted.map(row => row.nested.value)).toEqual([4, 3]);
    tables('b').toggle('nested.value');
    tables('b').toggle('nested.value');
    expect(tables('a').direction).toBe('asc');
    expect(tables('b').direction).toBe('desc');
    expect(sortField({}, 'scores.missing.value')).toBeUndefined();
  });
});
