import { describe, expect, it } from 'vitest';
import { useQuantTableSort } from '../useQuantTableSort';

describe('Quant table ordering', () => {
  it('toggles direction while leaving missing metrics last and preserving ties', () => {
    const rows = [{id:1,score:null},{id:2,score:.8},{id:3,score:.2},{id:4,score:.8},{id:5,score:NaN}];
    const sort = useQuantTableSort(() => rows, (row,key) => row[key as keyof typeof row], 'score');
    expect(sort.sorted.value.map(x=>x.id)).toEqual([3,2,4,1,5]);
    sort.toggle('score');
    expect(sort.direction.value).toBe('desc');
    expect(sort.sorted.value.map(x=>x.id)).toEqual([2,4,3,1,5]);
    expect(rows.map(x=>x.id)).toEqual([1,2,3,4,5]);
  });
});
