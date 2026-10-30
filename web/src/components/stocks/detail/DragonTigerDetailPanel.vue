<script setup lang="ts">
import { metricHint } from '@/utils/metricHints';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useTableSort, sortField } from '@/composables/useTableSort';
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { dragonTigerFlowApi, flowBoardLabels, type FlowFilters, type FlowOverview } from '@/api/dragonTigerFlow';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { stockEvidence, money } from '@/components/dragon-tiger-flow/display';
import { signedTextClass } from '@/utils/marketTone';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { StockDetailPanelProps } from './types';
const props = defineProps<StockDetailPanelProps>();
const filters = computed<FlowFilters>(() => props.context?.dragonTiger ?? {
  endDate: props.context?.tradeDate || '', days: 1, board: 'all', rangeDays: 1,
});
const data = shallowRef<FlowOverview | null>(null);
const selected = ref('');
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const stockRows = computed(() => stockEvidence(data.value, props.symbol));
const concepts = computed(() => {
  const entries = new Map<string, string>();
  for (const row of data.value?.evidence ?? []) if (row.symbol === props.symbol) entries.set(row.conceptId, row.conceptName);
  return [...entries].map(([id, name]) => ({ id, name }));
});
const contributions = computed(() => data.value?.evidence.filter(row => row.symbol === props.symbol && row.conceptId === selected.value) ?? []);
const hotDetails = computed(() => data.value?.hotMoneyDetails.filter(row => row.symbol === props.symbol) ?? []);
const moneyClass = (value: number | null) => signedTextClass(value);
let generation = 0;
async function load() {
  const token = ++generation;
  data.value = null; selected.value = ''; error.value = null; loading.value = false;
  if (props.market !== 'CN') return;
  loading.value = true;
  try {
    const response = await dragonTigerFlowApi.overview({ ...filters.value });
    if (token !== generation) return;
    data.value = response;
    selected.value = concepts.value.find(entry => entry.id === props.context?.dragonTigerConceptId)?.id ?? concepts.value[0]?.id ?? '';
  } catch (cause) { if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; } }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => filters.value.endDate, () => filters.value.days, () => filters.value.board, () => filters.value.rangeDays, () => props.context?.dragonTigerConceptId], load, { immediate: true });
onBeforeUnmount(() => { ++generation; });

const table = useTableSort(() => stockRows.value, (row, key) => key === 'concepts' ? row.concepts.join('、') : sortField(row, key));

</script>
<template>
  <div
    class="space-y-4"
    data-testid="dragon-tiger-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      正式龙虎榜 · {{ data?.dates[0] || filters.endDate || '最新可用日期' }} — {{ data?.tradeDate || '—' }} · {{ flowBoardLabels[filters.board] }} · {{ filters.rangeDays === 3 ? '3日榜独立截面，不累计' : `${filters.days}日观察窗口` }} · 金额单位亿元
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取龙虎榜证据…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
    />
    <p
      v-else-if="!stockRows.length && !hotDetails.length"
      class="text-sm text-muted-foreground"
    >
      {{ market === 'CN' ? '该股票在所选口径暂无上榜证据，不代表资金净额为零。' : '龙虎榜仅适用于 A 股市场。' }}
    </p>
    <Button
      v-if="error"
      variant="outline"
      @click="load"
    >
      重试
    </Button>
    <template v-if="data && (stockRows.length || hotDetails.length)">
      <p
        v-if="!data.complete"
        class="text-sm text-muted-foreground"
      >
        窗口不完整：{{ data.missingDates.join('、') }}。仅展示已采集记录，不补零。
      </p>
      <p class="text-xs text-muted-foreground">
        分类独立、可能重叠；游资缺失不是零。仅代表龙虎榜样本，不是全市场资金流。
      </p>
      <div class="overflow-x-auto">
        <p class="text-xs text-muted-foreground">
          股票原始净额与概念贡献分别列示；概念归属按各交易日观测保存。
        </p>
        <table class="w-full min-w-max text-sm">
          <thead>
            <tr>
              <SortableTableHeader
                class="p-2 text-left"
                label="日期 / 周期"
                :description="[metricHint('flow', '日期 / 周期'), '按交易日期排序'].filter(Boolean).join('；')"
                scope="flow"
                v-bind="table.header('tradeDate')"
              /><SortableTableHeader
                align="right"
                class="p-2 text-right"
                label="股票整体净额"
                scope="flow"
                v-bind="table.header('stockNetValue')"
              /><SortableTableHeader
                align="right"
                class="p-2 text-right"
                label="所选口径原始净额"
                scope="flow"
                v-bind="table.header('originalNetValue')"
              /><SortableTableHeader
                class="p-2 text-left"
                label="当日概念 / 每概念权重"
                :description="[metricHint('flow', '当日概念 / 每概念权重'), '按概念名称排序'].filter(Boolean).join('；')"
                scope="flow"
                v-bind="table.header('concepts')"
              />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in table.sorted"
              :key="row.tradeDate"
              class="border-t"
            >
              <td class="p-2 whitespace-nowrap">
                {{ row.tradeDate }} / {{ row.rangeDays }}日
              </td><td class="p-2 text-right">
                {{ money(row.stockNetValue) }}
              </td><td class="p-2 text-right">
                {{ money(row.originalNetValue) }}
              </td><td class="p-2">
                {{ row.concepts.join('、') || '未分类' }} · 1/{{ row.allocationCount }}
              </td>
            </tr>
          </tbody>
        </table>
        <label class="grid gap-2 text-sm">逐日分摊贡献 · 选择概念
          <select
            v-model="selected"
            aria-label="股票贡献概念"
            class="h-10 rounded-md border bg-background px-3"
          >
            <option
              v-for="entry in concepts"
              :key="entry.id"
              :value="entry.id"
            >{{ entry.name }}</option>
          </select>
        </label>
        <div
          v-for="row in contributions"
          :key="row.tradeDate"
          class="flex justify-between border-b py-2 text-sm"
        >
          <span>{{ row.tradeDate }} · 权重 1/{{ row.allocationCount }}</span>
          <span :class="moneyClass(row.netValue)">{{ money(row.netValue) }}</span>
        </div>
        <h3 class="font-semibold">
          游资明细 · 有限已命名样本
        </h3>
        <p
          v-if="!hotDetails.length"
          class="text-sm text-muted-foreground"
        >
          暂无可用游资明细，不代表游资净额为零。
        </p>
        <div
          v-for="(row, index) in hotDetails"
          :key="index"
          class="flex justify-between border-b py-2 text-sm"
        >
          <span>{{ row.tradeDate }} · {{ row.hotMoneyName }}</span><span :class="moneyClass(row.hotMoneyItemNetValue)">{{ money(row.hotMoneyItemNetValue) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
