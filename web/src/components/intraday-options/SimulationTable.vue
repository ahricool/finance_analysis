<script setup lang="ts" generic="T extends object">
import { useTableSort } from '@/composables/useTableSort';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
const props = defineProps<{
  rows: T[];
  columns: Array<{ key: string; label: string; numeric?: boolean }>;
  value: (row: T, key: string) => unknown;
  rowKey: (row: T) => string | number;
  rowTestid?: string;
  label: string;
  empty: string;
}>();
defineSlots<{ cell(props: { row: T; column: string }): unknown }>();
const table = useTableSort(() => props.rows, (row, key) => props.value(row, key));
</script>

<template>
  <Table :aria-label="label">
    <caption class="sr-only">
      {{ label }}
    </caption>
    <TableHeader class="bg-muted/40">
      <TableRow>
        <SortableTableHeader
          v-for="column in columns"
          :key="column.key"
          :label="column.label"
          :align="column.numeric ? 'right' : 'left'"
          v-bind="table.header(column.key)"
        />
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow
        v-for="row in table.sorted"
        :key="rowKey(row)"
        :data-testid="rowTestid"
        class="hover:bg-muted/30"
      >
        <TableCell
          v-for="column in columns"
          :key="column.key"
          class="px-4 py-3 align-top"
          :class="column.numeric ? 'text-right tabular-nums' : ''"
        >
          <slot
            name="cell"
            :row="row"
            :column="column.key"
          />
        </TableCell>
      </TableRow>
      <TableRow v-if="!rows.length">
        <TableCell
          :colspan="columns.length"
          class="h-24 text-center text-sm text-muted-foreground"
        >
          {{ empty }}
        </TableCell>
      </TableRow>
    </TableBody>
  </Table>
</template>
