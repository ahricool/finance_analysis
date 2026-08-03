import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

describe('Table', () => {
  it('renders component-based table markup in a native horizontal scroll container', () => {
    const wrapper = mount({
      components: { Table, TableBody, TableCell, TableHead, TableHeader, TableRow },
      template: `
        <Table>
          <TableHeader><TableRow><TableHead>名称</TableHead></TableRow></TableHeader>
          <TableBody><TableRow><TableCell>示例</TableCell></TableRow></TableBody>
        </Table>
      `,
    });

    expect(wrapper.get('[data-slot="table-container"]').classes()).toContain('overflow-x-auto');
    expect(wrapper.get('[data-slot="table"]').classes()).toContain('min-w-max');
    expect(wrapper.findAll('table')).toHaveLength(1);
  });
});
