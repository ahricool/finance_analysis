<script setup lang="ts">
import { getDisplayTimezone, formatFullDateTimeWithTimezone } from '@/utils/format';
import { computed, ref, watch } from 'vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { contractsApi, type HistorySample } from '@/api/contracts';
import FieldSelect from '@/components/forms/FieldSelect.vue';

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ symbol: string; boundary?: number }>();
const options = [
  { value: '', label: '收起历史副图' }, { value: 'accounts', label: '全市场账户多空比（倍）' },
  { value: 'top_accounts', label: '大户账户多空比（倍）' }, { value: 'top_positions', label: '大户持仓多空比（倍）' },
  { value: 'oi', label: 'OI 数量' }, { value: 'taker', label: '5m 主动买入占比（%）' },
];
const selected = ref('');
const visible = computed(() => !!selected.value);
const rows = ref<HistorySample[]>([]);
const status = ref('');
watch([() => props.symbol, () => props.boundary, visible], async ([symbol, boundary, show], _, cleanup) => {
  rows.value = [];
  if (!show) return;
  const controller = new AbortController();
  cleanup(() => controller.abort());
  const end = boundary ?? Math.floor(Date.now() / 300000) * 300000;
  status.value = '历史加载中…';
  try {
    const values = await contractsApi.history(symbol, end - 287 * 300000, end, controller.signal);
    if (!controller.signal.aborted) { rows.value = values; status.value = ''; }
  } catch {
    if (!controller.signal.aborted) status.value = '历史查询失败';
  }
}, { immediate: true });
function value(row: HistorySample) {
  switch (selected.value) {
    case 'accounts': return row.accounts?.ratio;
    case 'top_accounts': return row.top_accounts?.ratio;
    case 'top_positions': return row.top_positions?.ratio;
    case 'oi': return row.oi?.quantity;
    case 'taker': {
      const t = row.taker;
      return t && t.buy + t.sell > 0 ? 100 * t.buy / (t.buy + t.sell) : null;
    }
    default: return null;
  }
}
const points = computed(() => rows.value.map(row => [row.timestamp, value(row) ?? null] as const));
const observed = computed(() => points.value.filter(p => p[1] != null));
const option = computed(() => {
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: getDisplayTimezone(), month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  const axisPointer = { label: { formatter: ({ value }: { value: number }) => formatter.format(value) } };
  const data: [number, number | null][] = [];
  for (const [stamp, y] of points.value) {
    const prev = data.at(-1);
    if (prev && stamp - prev[0] > 300000) data.push([prev[0] + 300000, null]);
    data.push([stamp, y]);
  }
  return {
    animation: false, useUTC: true, tooltip: { trigger: 'axis' },
    grid: { containLabel: true, left: 12, right: 18, top: 12, bottom: 12 },
    xAxis: { type: 'time', axisLabel: { formatter: (value: number) => formatter.format(value) }, axisPointer }, yAxis: { type: 'value', scale: true },
    series: [{ type: 'line', name: options.find(o => o.value === selected.value)?.label, data, showSymbol: observed.value.length === 1 }],
  };
});

</script>

<template>
  <div class="space-y-2 border-t pt-3">
    <FieldSelect
      v-model="selected"
      class="w-56"
      :options="options"
      label="5 分钟历史副图"
    />
    <template v-if="visible">
      <p
        v-if="observed.length"
        class="text-xs text-muted-foreground"
      >
        {{ formatFullDateTimeWithTimezone(observed[0]![0]) }} 至 {{ formatFullDateTimeWithTimezone(observed.at(-1)![0]) }}
      </p>
      <div
        v-if="observed.length"
        class="h-48 w-full"
      >
        <VChart
          :option="option"
          autoresize
        />
      </div>
      <p
        v-else
        class="text-sm text-muted-foreground"
      >
        {{ status || '暂无该指标的历史样本' }}
      </p>
    </template>
  </div>
</template>
