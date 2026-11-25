<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Row } from '@/api/paperTrade';
import { useTableSort, sortField, sortNumber } from '@/composables/useTableSort';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import AppPagination from '@/components/app/AppPagination.vue';

export interface Column { key: string; label: string; numeric?: boolean; time?: boolean }
const props = defineProps<{ rows: Row[]; columns: Column[]; actions?: boolean }>();
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
    const date = new Date(typeof value === 'number' ? value : String(value));
    return Number.isNaN(date.getTime()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 19);
  }
  if (typeof value === 'boolean') return value ? '已启用' : '已暂停';
  if (typeof value === 'string' && labels[value]) return labels[value] + ' · ' + value;
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
</script>

<template>
  <div class="min-w-0 space-y-3">
    <div class="overflow-x-auto rounded-md border">
      <table class="w-full text-sm">
        <thead class="bg-muted/50">
          <tr>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              v-bind="sort.header(column.key)"
              :align="column.numeric ? 'right' : 'left'"
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
          <tr
            v-for="(row, index) in visible"
            :key="index"
            class="border-t"
          >
            <td
              v-for="column in columns"
              :key="column.key"
              class="whitespace-nowrap px-4 py-2 tabular-nums"
              :class="column.numeric && 'text-right'"
            >
              {{ display(row, column) }}
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
          </tr>
          <tr v-if="!rows.length">
            <td
              :colspan="columns.length + Number(!!actions)"
              class="py-8 text-center text-muted-foreground"
            >
              暂无记录
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <AppPagination
      :current-page="page"
      :total-pages="pages"
      @page-change="page = $event"
    />
  </div>
</template>
