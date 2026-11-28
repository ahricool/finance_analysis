<script setup lang="ts" generic="T extends object">
import InstrumentTable from '@/components/market-data/instrument-table/InstrumentTable.vue';
import InstrumentRow from '@/components/market-data/instrument-table/InstrumentRow.vue';
import { useTableSort } from '@/composables/useTableSort';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
const props = defineProps<{
  rows: T[];
  symbol?: (row: T) => string;
  columns: Array<{ key: string; label: string; numeric?: boolean }>;
  value: (row: T, key: string) => unknown;
  rowKey: (row: T) => string | number;
  rowTestid?: string;
  defaultTimeKey?: string;
  label: string;
  empty: string;
}>();
defineSlots<{ cell(props: { row: T; column: string }): unknown }>();
const table = useTableSort(() => props.rows, (row, key) => props.value(row, key));
if (props.defaultTimeKey) {
  table.sortKey = props.defaultTimeKey;
  table.direction = 'desc';
}
</script>

<template>
  <InstrumentTable
    :charts="!!symbol"
    :aria-label="label"
  >
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
          :class="{ 'instrument-column': column.key === 'symbol' }"
        />
      </TableRow>
    </TableHeader>
    <TableBody>
      <InstrumentRow
        v-for="row in table.sorted"
        :key="rowKey(row)"
        :symbol="symbol?.(row)"
        :row-id="rowKey(row)"
        market="US"
        :data-testid="rowTestid"
        class="hover:bg-muted/30"
      >
        <TableCell
          v-for="column in columns"
          :key="column.key"
          class="px-4 py-3 align-top"
          :class="{ 'instrument-column': column.key === 'symbol', 'text-right tabular-nums': column.numeric }"
        >
          <slot
            name="cell"
            :row="row"
            :column="column.key"
          />
        </TableCell>
      </InstrumentRow>
      <TableRow v-if="!rows.length">
        <TableCell
          :colspan="columns.length"
          class="h-24 text-center text-sm text-muted-foreground"
        >
          {{ empty }}
        </TableCell>
      </TableRow>
    </TableBody>
  </InstrumentTable>
</template>
