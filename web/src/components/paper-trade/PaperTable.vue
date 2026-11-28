<script setup lang="ts">
import { formatFullDateTimeWithTimezone } from '@/utils/format';
import ContractLink from '@/components/contracts/ContractLink.vue';
import ContractRowChart from '@/components/contracts/ContractRowChart.vue';
import InstrumentTable from '@/components/market-data/instrument-table/InstrumentTable.vue';
import InstrumentRow from '@/components/market-data/instrument-table/InstrumentRow.vue';
import { computed, ref, watch } from 'vue';
import type { Row } from '@/api/paperTrade';
import { useTableSort, sortField, sortNumber } from '@/composables/useTableSort';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import AppPagination from '@/components/app/AppPagination.vue';

import type { ContractQuote } from '@/api/contracts';

export interface Column { key: string; label: string; numeric?: boolean; time?: boolean }
const props = defineProps<{ rows: Row[]; columns: Column[]; actions?: boolean; contracts?: Map<string, ContractQuote> }>();
const contractTable = computed(() => props.columns.some(col => col.key === 'symbol'));
function contractSymbol(row: Row) { return contractTable.value && typeof row.symbol === 'string' ? row.symbol : ''; }
function recordKey(row: Row) {
  return JSON.stringify([row.symbol, row.id, row.algoId, row.orderId, row.positionSide, row.time, row.tranId, row.incomeType, row.asset]);
}
function contract(row: Row): ContractQuote {
  const symbol = contractSymbol(row);
  return props.contracts?.get(symbol) ?? { symbol, underlying_symbol: null, category: '', quote: null };
}
const sort = useTableSort(() => props.rows, (row, key) => {
  const value = sortField(row, key);
  const column = props.columns.find(c => c.key === key);
  return column?.time ? (typeof value === 'number' ? value : Date.parse(String(value))) :
    column?.numeric ? sortNumber(value) : value;
});
const page = ref(1);
const pages = computed(() => Math.max(1, Math.ceil(props.rows.length / 10)));
const visible = computed(() => sort.sorted.slice((page.value - 1) * 10, page.value * 10));
watch(() => sort.sortKey + sort.direction, () => { page.value = 1; });
watch(pages, value => { page.value = Math.min(page.value, value); });
const labels: Record<string, string> = {
  ema_cross: 'EMA 交叉', perpetual_drive: '24/7 永续驱动 (V8)',
  STRATEGY: 'FA 策略', FA_MANUAL: 'FA 手动', EXTERNAL: 'App / 外部', CONFLICT: '外部冲突',
  OBSERVED: '观察', QUEUED: '待提交', SUBMITTING: '提交中', UNKNOWN: '待核对',
  SUBMITTED: '已委托', PARTIALLY_FILLED: '部分成交', FILLED: '已成交', CANCELED: '已取消',
  FAILED: '失败', BLOCKED: '条件未通过', FINISHED: 'Algo 已结束', PAUSED: '已暂停',
  WAITING: '等待信号', NEW: '挂单', TRIGGERED: '已触发', EXPIRED: '已失效', REJECTED: '已拒绝',
  LONG: '多头', SHORT: '空头', BOTH: '双向 / 净头寸', BUY: '买', SELL: '卖',
  SIGNAL: '开仓信号', CLOSE: '平仓', PROTECT: '保护单', CANCEL: '撤单', MANUAL: '手动委托',
};
function display(row: Row, column: Column) {
  const value = sortField(row, column.key);
  if (value == null || value === '') return '—';
  if (column.time) {
    return formatFullDateTimeWithTimezone(typeof value === 'number' ? value : String(value));
  }
  if (typeof value === 'boolean') return value ? '已启用' : '已暂停';
  if (typeof value === 'string' && labels[value]) return labels[value] + ' · ' + value;
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
</script>

<template>
  <div class="min-w-0 space-y-3">
    <div class="overflow-x-auto rounded-md border">
      <InstrumentTable
        :charts="contractTable"
        class="w-full text-sm"
      >
        <thead class="bg-muted/50">
          <tr>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              v-bind="sort.header(column.key)"
              :align="column.numeric ? 'right' : 'left'"
              :class="{ 'instrument-column': column.key === 'symbol' }"
            />
            <th
              v-if="actions"
              class="px-4"
            >
              操作
            </th>
          </tr>
        </thead>
        <tbody>
          <InstrumentRow
            v-for="(row, index) in visible"
            :key="contractSymbol(row) ? recordKey(row) : index"
            :symbol="contractSymbol(row)"
            :row-id="recordKey(row)"
            class="border-t"
          >
            <td
              v-for="column in columns"
              :key="column.key"
              class="whitespace-nowrap px-4 py-2 tabular-nums"
              :class="{ 'instrument-column': column.key === 'symbol', 'text-right': column.numeric }"
            >
              <ContractLink
                v-if="column.key === 'symbol' && contractSymbol(row)"
                :symbol="contractSymbol(row)"
                :contract="contract(row)"
              />
              <template v-else>
                {{ display(row, column) }}
              </template>
            </td>
            <td
              v-if="actions"
              class="whitespace-nowrap px-4 py-2"
            >
              <slot
                name="actions"
                :row="row"
              />
            </td>
            <template #chart="{ period }">
              <ContractRowChart
                :row="contract(row)"
                :period="period"
              />
            </template>
          </InstrumentRow>
          <tr v-if="!rows.length">
            <td
              :colspan="columns.length + Number(!!actions)"
              class="py-8 text-center text-muted-foreground"
            >
              暂无记录
            </td>
          </tr>
        </tbody>
      </InstrumentTable>
    </div>
    <AppPagination
      :current-page="page"
      :total-pages="pages"
      @page-change="page = $event"
    />
  </div>
</template>
