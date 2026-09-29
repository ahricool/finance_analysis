import type { SheetData } from 'write-excel-file/browser';

export interface ExcelColumn {
  label: string;
  format?: string;
}
export type ExcelValue = string | number | boolean | null | undefined;

export function buildExcelData(columns: readonly ExcelColumn[], rows: ExcelValue[][]): SheetData {
  return [
    columns.map(column => ({ type: String, value: column.label, fontWeight: 'bold', wrap: true })),
    ...rows.map(row => columns.map((column, index) => {
      const value = row[index];
      if (value == null || (typeof value === 'number' && !Number.isFinite(value))) return null;
      if (typeof value === 'number') return { type: Number, value, format: column.format };
      // Explicit string cells preserve codes and never interpret names as formulas.
      return { type: String, value: typeof value === 'boolean' ? (value ? '是' : '否') : value };
    })),
  ];
}

export async function exportExcel(fileName: string, sheet: string, columns: readonly ExcelColumn[], rows: ExcelValue[][]) {
  const { default: writeExcelFile } = await import('write-excel-file/browser');
  await writeExcelFile(buildExcelData(columns, rows), {
    sheet,
    stickyRowsCount: 1,
    columns: columns.map(column => ({ width: Math.min(36, Math.max(16, column.label.length + 4)) })),
  }).toFile(fileName);
}
