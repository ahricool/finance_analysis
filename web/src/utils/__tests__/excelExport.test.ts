import { describe, expect, it } from 'vitest';
import { buildExcelData } from '../excelExport';

describe('Excel table cells', () => {
  it('preserves numeric percentages, zero, literal text, and missing values', () => {
    const data = buildExcelData([{ label: '收益', format: '0.00%' }, { label: '代码' }], [
      [0.125, '000001'], [0, '=HYPERLINK("bad")'], [null, false], [NaN, undefined],
    ]);
    expect(data[1]).toEqual([{ type: Number, value: 0.125, format: '0.00%' }, { type: String, value: '000001' }]);
    expect(data[2]).toEqual([{ type: Number, value: 0, format: '0.00%' }, { type: String, value: '=HYPERLINK("bad")' }]);
    expect(data[3]).toEqual([null, { type: String, value: '否' }]);
    expect(data[4]).toEqual([null, null]);
  });
});
