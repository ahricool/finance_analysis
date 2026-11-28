<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { fetchIntradayMarket, type IntradayBar } from '@/api/intradayMarket';
import type { SimulationSnapshot, TrendResult } from '@/api/intradayOptions';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import TradingSessionLegend from '@/components/market-data/TradingSessionLegend.vue';
import { tradingSessionOverlays } from '@/components/market-data/tradingSessionOverlay';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import TableExpansionPanel from '@/components/market-data/TableExpansionPanel.vue';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/composables/useTheme';
import { clock, directions, fmt, pct, structureName, structurePhases } from './labels';
import OpportunityPanel from './OpportunityPanel.vue';
import { referenceSeries, structureOverlays, trendOverlays } from './overlays';
import { simulationOperations, simulationMarkers, simulationTradeOverlays } from './simulationMarkers';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import SimulationTable from './SimulationTable.vue';
import { sortField, sortTime } from '@/composables/useTableSort';

import { queueTableRequest } from '@/utils/tableRequests';

const props = defineProps<{ symbol: string; result: TrendResult | null; stale: boolean; simulation?: SimulationSnapshot | null }>();
const selected = ref(30);
const showTrades = ref(true);
const selectedTradeMinute = ref('');
const focusRequest = ref(0);
const mode = ref<'vwap' | 'mean' | 'off'>('vwap');
const rows = shallowRef<IntradayBar[]>([]);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const chartDate = ref('');
const { resolvedTheme } = useTheme();
const closed = computed(() => rows.value.filter(b => b.confirmed));
const bars = computed(() => closed.value.map(b => ({ ...b, turnover: b.turnover ?? undefined })));
const current = computed(() => {
  const b = rows.value.find(row => !row.confirmed);
  return b ? { ...b, turnover: b.turnover ?? undefined } : null;
});
const window = computed(() => props.result?.windows.find(w => w.minutes === selected.value));
const tradeOperations = computed(() => simulationOperations(props.simulation, props.symbol, chartDate.value));
const tradeMarkers = computed(() => simulationMarkers(tradeOperations.value, rows.value));
const selectedTrade = computed(() => tradeMarkers.value.find(m => String(m.timestamp) === selectedTradeMinute.value));
const unplottedTrades = computed(() => tradeOperations.value.length - tradeMarkers.value.reduce((n, m) => n + m.operations.length, 0));
function selectTrade(timestamp: number) { selectedTradeMinute.value = String(timestamp); focusRequest.value++; }
watch([() => props.symbol, chartDate], () => { selectedTradeMinute.value = ''; });
const tradeColumns = [
  { key: 'label', label: '模拟动作' }, { key: 'price', label: '模拟价格', numeric: true },
  { key: 'at', label: '进退场 / 计划时间' }, { key: 'priceAt', label: '价格时间' },
  { key: 'processedAt', label: '实际处理时间' }, { key: 'reason', label: '原因' },
];
const timestampLabel = (at: string | undefined) => at ? new Date(at).toLocaleString('zh-CN', { timeZone: 'America/New_York', hour12: false }) : '未知';
const overlays = computed(() => [...tradingSessionOverlays(rows.value), ...trendOverlays(closed.value, window.value, mode.value, resolvedTheme.value === 'dark'),
  ...structureOverlays(props.result?.structure),
  ...(showTrades.value ? simulationTradeOverlays(tradeMarkers.value, resolvedTheme.value === 'dark', selectTrade) : [])]);
const referenceLabel = computed(() => mode.value === 'off' ? '参考线已隐藏' : referenceSeries(closed.value, mode.value).label);
let historyVersion: string | null | undefined;
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0, stopped = false;
async function load() {
  if (stopped || controller) return;
  const owner = generation;
  const request = new AbortController(); controller = request;
  try {
    const since = rows.value.at(-1)?.timestamp;
    const result = await queueTableRequest(request.signal, () => fetchIntradayMarket(props.symbol, since == null ? undefined : new Date(since).toISOString(), request.signal, historyVersion));
    if (stopped || owner !== generation) return;
    const merged = new Map((result.reset || result.fullSnapshot ? [] : rows.value).map(b => [b.timestamp, b]));
    result.items.forEach(b => merged.set(b.timestamp, b));
    rows.value = [...merged.values()].sort((a, b) => a.timestamp - b.timestamp);
    chartDate.value = result.tradingDate;
    historyVersion = result.historyVersion;
    error.value = null;
  } catch (reason) {
    if (!stopped && owner === generation && !request.signal.aborted) error.value = getParsedApiError(reason);
  } finally {
    if (owner === generation) { controller = null; loading.value = false; if (!stopped) timer = setTimeout(() => { void load(); }, 5000); }
  }
}
watch(() => props.symbol, () => {
  generation++; controller?.abort(); controller = null; clearTimeout(timer); rows.value = []; chartDate.value = ''; historyVersion = undefined;
  loading.value = true; error.value = null; void load();
}, { immediate: true });
onBeforeUnmount(() => { stopped = true; generation++; controller?.abort(); clearTimeout(timer); });
</script>

<template>
  <TableExpansionPanel data-testid="options-trend-panel">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <strong class="text-sm">{{ symbol }} · {{ chartDate || '当日' }} · 最近24小时1分钟K线</strong>
      <span class="text-xs text-muted-foreground">纽约时间 · 全天闭合分钟线参与评分</span>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-muted-foreground">观察范围</span>
      <Button
        v-for="n in [5, 15, 30, 60]"
        :key="n"
        size="sm"
        :variant="selected === n ? 'secondary' : 'ghost'"
        :aria-pressed="selected === n"
        @click="selected = n"
      >
        {{ n }}分钟
      </Button>
      <span class="ml-2 text-xs text-muted-foreground">参考线</span>
      <Button
        v-for="item in [{ key: 'vwap', label: 'VWAP' }, { key: 'mean', label: '等权均价' }, { key: 'off', label: '隐藏' }] as const"
        :key="item.key"
        size="sm"
        :variant="mode === item.key ? 'secondary' : 'ghost'"
        :aria-pressed="mode === item.key"
        @click="mode = item.key"
      >
        {{ item.label }}
      </Button>
    </div>
    <TradingSessionLegend v-if="rows.length" />
    <MarketKLineChart
      v-if="rows.length"
      :key="symbol"
      :symbol="symbol"
      period="1m"
      live-snapshot
      full-minute-window
      :bars="bars"
      :current="current"
      :overlays="overlays"
      :focus-timestamp="showTrades && selectedTrade ? selectedTrade.timestamp : undefined"
      :focus-request="focusRequest"
      timezone="America/New_York"
    />
    <p
      v-else
      class="py-10 text-center text-sm text-muted-foreground"
    >
      {{ loading ? '加载分钟行情…' : '暂无当日分钟线；不会补造缺失K线。' }}
    </p>
    <p class="text-xs text-muted-foreground">
      {{ referenceLabel }}。紫色区域仅标记所选窗口；窗口尚未完整时不标记。
    </p>
    <div
      class="flex flex-wrap items-center gap-3"
      data-testid="simulation-chart-markers"
    >
      <Button
        variant="outline"
        size="sm"
        :aria-pressed="showTrades"
        @click="showTrades = !showTrades"
      >
        模拟 B/S {{ showTrades ? '已显示' : '已隐藏' }}
      </Button>
      <FieldSelect
        :model-value="selectedTradeMinute"
        class="w-full sm:w-72"
        aria-label="定位模拟成交"
        placeholder="选择成交，定位 K 线"
        :disabled="!tradeMarkers.length"
        :options="tradeMarkers.map(m => ({ value: String(m.timestamp), label: `${clock(new Date(m.timestamp).toISOString())} · ${m.label} · ${m.operations.length}条模拟记录` }))"
        @update:model-value="value => { showTrades = true; selectTrade(Number(value)); }"
      />
      <span class="text-xs text-muted-foreground">{{ tradeOperations.length }} 条模拟进退场</span>
    </div>
    <p class="text-xs leading-relaxed text-muted-foreground">
      模拟 B：做多进场 / 做空退场；S：做空进场 / 做多退场；B/S：同分钟多个动作。点击标记查看记录，非真实成交。
      * 为估算退出，按计划退出时间定位，价格来自历史有效报价，不能视为该时刻成交。
      <span v-if="unplottedTrades">{{ unplottedTrades }} 条记录对应分钟 K 缺失，未移到相邻 K 线。</span>
    </p>
    <div
      v-if="selectedTrade"
      class="overflow-hidden rounded-lg border"
      data-testid="simulation-trade-detail"
    >
      <h3 class="border-b bg-muted/30 px-4 py-3 text-sm font-semibold">
        {{ symbol }} · 模拟 {{ selectedTrade.label }} 记录（纽约时间）
      </h3>
      <SimulationTable
        :rows="selectedTrade.operations"
        :columns="tradeColumns"
        default-time-key="at"
        :row-key="op => op.id"
        :value="(op, key) => ['at', 'priceAt', 'processedAt'].includes(key) ? sortTime(sortField(op, key) as string | undefined) : sortField(op, key)"
        label="模拟成交标记明细"
        empty="暂无记录"
      >
        <template #cell="{ row: op, column }">
          <template v-if="column === 'label'">
            {{ op.action }} · {{ op.label }}{{ op.estimated ? '（估算）' : '' }}
          </template>
          <template v-else-if="column === 'price'">
            {{ fmt(op.price, 2) }}
          </template>
          <template v-else-if="column === 'reason'">
            <p class="max-w-sm whitespace-normal">
              {{ op.reason }}
            </p>
          </template>
          <template v-else>
            {{ timestampLabel(sortField(op, column) as string | undefined) }}
          </template>
        </template>
      </SimulationTable>
    </div>
    <OpportunityPanel
      :opportunities="result?.opportunities"
      :plans="simulation?.states.find(s => s.symbol === symbol)?.plans"
      :stale="stale"
    />
    <article
      v-if="result?.structure"
      class="space-y-1 rounded border p-3 text-sm"
      data-testid="structure-detail"
    >
      <p class="font-medium">
        短线结构：{{ structureName(result.structure) }} · {{ structurePhases[result.structure.phase] }}
      </p>
      <p class="text-xs text-muted-foreground">
        {{ directions[result.structure.background] }}背景 · 截至 {{ clock(result.structure.asOf) }} · 可用{{ result.structure.availableBars }}根 / 缺{{ result.structure.missingBars }}根
      </p>
      <p
        v-if="result.structure.box"
        class="text-xs"
      >
        固定箱体 {{ fmt(result.structure.box.lower, 2) }}–{{ fmt(result.structure.box.upper, 2) }} · 形成区间 {{ clock(result.structure.box.startAt) }}–{{ clock(result.structure.box.endAt) }}
      </p>
      <p
        v-if="result.structure.confirmedAt"
        class="text-xs text-muted-foreground"
      >
        突破首次确认 {{ clock(result.structure.confirmedAt) }} · 当前阶段发生 {{ clock(result.structure.since) }}
      </p>
      <p
        v-for="reason in result.structure.reasons"
        :key="reason"
        class="text-xs"
      >
        {{ reason }}
      </p>
      <p class="text-xs text-muted-foreground">
        橙线标出箱体边界，▼ 指向已确认高点，▲ 指向已确认低点，◆ 标出当前突破阶段。悬停可查看标记含义。拐点需右侧2根K闭合才确认。结构描述与入场确认分开，机会分支另行判断，不代表买卖指令。
      </p>
    </article>
    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <article
        v-for="w in result?.windows ?? []"
        :key="w.minutes"
        class="space-y-1 rounded border p-3 text-xs"
        :class="selected === w.minutes ? 'border-brand/50' : ''"
      >
        <p class="text-sm font-medium">
          {{ w.minutes }}分钟 · {{ fmt(w.score) }}分 · {{ pct(w.returnPct) }}
        </p>
        <p
          v-if="w.dataStatus !== 'ready'"
          class="text-muted-foreground"
        >
          {{ w.dataStatus === 'warming' ? '窗口不足 · ' : '分钟缺失 · ' }}缺{{ w.missingBars ?? '部分' }}根 · 可用{{ w.availableBars ?? '—' }}根 · {{ w.score == null ? '数据过少，无法计算' : '参考分' }}
        </p>
        <template v-if="w.score != null">
          <p>稳定度 {{ fmt(w.stability) }} · 路径效率 {{ fmt(w.efficiency) }}</p>
          <p>移动强度 {{ fmt(w.strength) }} · 扰动控制 {{ fmt(w.disturbance) }}</p>
          <p>标准化移动 {{ fmt(w.normalizedMove, 2) }} · 逆向幅度 {{ fmt(w.adverseMove, 2) }}</p>
          <p>最长逆向占比 {{ fmt((w.adverseDuration ?? 0) * 100) }}% · 移动门槛系数 {{ fmt(w.movementGate, 2) }}</p>
          <p>单分钟移动集中度 {{ fmt((w.concentration ?? 0) * 100) }}%</p>
          <p class="text-muted-foreground">
            {{ clock(w.startAt) }}–{{ clock(w.endAt) }}
          </p>
          <p
            v-for="reason in w.reasons"
            :key="reason"
            class="text-amber-600 dark:text-amber-400"
          >
            {{ reason }}
          </p>
        </template>
      </article>
    </div>
    <div class="space-y-1 text-sm">
      <p
        v-if="stale"
        class="text-amber-600 dark:text-amber-400"
      >
        以下为上次计算结果，不代表当前行情。
      </p>
      <p>{{ result?.explanation ?? '等待行情与完整窗口。' }}</p>
      <p class="text-xs text-muted-foreground">
        评分截至 {{ clock(result?.asOf) }} · 基础分 {{ fmt(result?.baseScore) }} · 方向一致性 {{ fmt(result?.alignment, 2) }} · 短线偏离 {{ fmt(result?.extensionAtr, 2) }} ATR
      </p>
      <p class="text-xs text-muted-foreground">
        窗口权重：稳定度30% / 路径效率30% / 移动强度25% / 扰动控制15%；综合窗口权重15m/30m/60m = 30%/45%/25%。5分钟仅作短线观察，不参与综合分。趋势质量分不是盈利概率，不与日内机会分直接相加。
      </p>
    </div>
  </TableExpansionPanel>
</template>
