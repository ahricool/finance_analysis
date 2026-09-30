<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { exportExcel } from '@/utils/excelExport';
import { toast } from 'vue-sonner';
import type { EventStudySummaryResponse, EventStudyEventsResponse, StrategyKey, StudyGroup, StudyEvent, StudyRegime, TrendMarket, EvaluationStatus } from '@/types/trendFollowing';

const props = defineProps<{ market: TrendMarket; endDate: string }>();
const end = ref(props.endDate);
const start = ref('');
const range = ref<number | 'custom'>(60);
const regime = ref<StudyRegime>('ALL');
const selected = ref<StrategyKey | null>(null);
const offset = ref(0);
const loading = ref(false);
const eventsLoading = ref(false);
const error = ref<ParsedApiError | null>(null);
const eventsError = ref<ParsedApiError | null>(null);
const result = shallowRef<EventStudySummaryResponse | null>(null);
const page = shallowRef<EventStudyEventsResponse | null>(null);
const groups = computed(() => result.value?.groups.filter(group => group.regime === applied.value.regime) ?? []);
const labels: Record<StrategyKey, string> = { TREND_FOLLOWING: '趋势', BOX_BREAKOUT: '箱体突破', PULLBACK_RESUME: '趋势回调', MEAN_REVERSION: '超跌反弹' };
const applied = ref({ start: '', end: '', regime: 'ALL' as StudyRegime });
let controller: AbortController | undefined;
let eventsController: AbortController | undefined;
function preset(value: number | 'custom') {
  range.value = value;
  if (value === 'custom') return;
  end.value = props.endDate;
  const date = new Date(`${end.value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - value);
  start.value = date.toISOString().slice(0, 10);
}
const invalidRange = computed(() => !start.value || !end.value || start.value > end.value || end.value > props.endDate
  || (Date.parse(end.value) - Date.parse(start.value)) / 86400000 > 730);
async function query() {
  if (invalidRange.value) return;
  controller?.abort();
  eventsController?.abort();
  eventsLoading.value = false;
  eventsError.value = null;
  selected.value = null;
  offset.value = 0;
  page.value = null;
  applied.value = { start: start.value, end: end.value, regime: regime.value };
  const request = new AbortController();
  controller = request;
  error.value = null;
  result.value = null;
  loading.value = true;
  try {
    const response = await trendFollowingApi.eventStudySummary(props.market, applied.value.start, applied.value.end, applied.value.regime, request.signal);
    if (!request.signal.aborted) result.value = response;
  } catch (e) {
    if (!request.signal.aborted) error.value = getParsedApiError(e);
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
async function loadEvents() {
  if (!selected.value) return;
  eventsController?.abort();
  const request = new AbortController();
  eventsController = request;
  eventsLoading.value = true;
  eventsError.value = null;
  page.value = null;
  try {
    const response = await trendFollowingApi.eventStudyEvents(props.market, applied.value.start, applied.value.end,
      applied.value.regime, selected.value, offset.value, request.signal);
    if (!request.signal.aborted) page.value = response;
  } catch (e) {
    if (!request.signal.aborted) eventsError.value = getParsedApiError(e);
  } finally {
    if (!request.signal.aborted) eventsLoading.value = false;
  }
}
// Date/regime controls only edit drafts. A market switch starts a fresh default study.
watch(() => props.market, () => { regime.value = 'ALL'; preset(60); void query(); }, { immediate: true });
watch(() => props.endDate, () => { if (range.value !== 'custom') preset(range.value); });
onBeforeUnmount(() => { controller?.abort(); eventsController?.abort(); });

const columns = [
  { key: 'strategy', label: '策略' }, { key: 'eventCount', label: 'N' },
  ...[5, 10, 20].flatMap(days => [{ key: `win${days}`, label: `${days}D 胜率` },
    ...(days === 5 ? [] : [{ key: `excess${days}`, label: `${days}D 平均超额` }])]),
  { key: 'mfe20', label: 'MFE20' }, { key: 'mae20', label: 'MAE20' },
  { key: 'coverage', label: '覆盖率' },
];
const sortKey = ref('strategy');
const direction = ref<'asc' | 'desc'>('asc');
function value(group: StudyGroup, key: string): number | string | null {
  if (key === 'strategy') return labels[group.strategy];
  if (key === 'eventCount') return group.eventCount;
  if (key === 'coverage') return group.featureCoverage;
  if (key === 'mfe20' || key === 'mae20') return group[key].mean;
  const horizon = group.horizons.find(item => item.days === Number(key.replace(/\D/g, '')));
  return (key.startsWith('win') ? horizon?.winRate : horizon?.meanExcessReturn) ?? null;
}
const sorted = computed(() => [...groups.value].sort((a, b) => {
  const x = value(a, sortKey.value), y = value(b, sortKey.value);
  if (x == null) return y == null ? a.strategy.localeCompare(b.strategy) : 1;
  if (y == null) return -1;
  return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y)))
    * (direction.value === 'asc' ? 1 : -1) || a.strategy.localeCompare(b.strategy);
}));
function toggleSort(key: string) {
  direction.value = sortKey.value === key ? direction.value === 'asc' ? 'desc' : 'asc' : 'desc';
  sortKey.value = key;
}
function choose(strategy: StrategyKey) { selected.value = strategy; offset.value = 0; void loadEvents(); }
function turnPage(value: number) { offset.value = value; void loadEvents(); }
const chosenGroup = computed(() => groups.value.find(group => group.strategy === selected.value));
const pct = (v: number | null | undefined) => v == null ? '—' : `${(v * 100).toFixed(1)}%`;
const statusText = (status: EvaluationStatus) => status === 'pending' ? '未到期' : status === 'missing' ? '缺行情' : '—';
function point(event: StudyEvent, days: number, excess = false) {
  const p = event.horizons.find(item => item.days === days);
  if (!p) return '—';
  return (excess ? p.excessStatus : p.status) === 'available' ? pct(excess ? p.excessReturn : p.value) : statusText(excess ? p.excessStatus : p.status);
}
const contextKeys: Record<StrategyKey, [string, string][]> = {
  TREND_FOLLOWING: [['alphaScore', 'Alpha'], ['trendScore', 'Trend'], ['rsScore', 'RS'], ['trendLifecycle', 'Lifecycle']],
  BOX_BREAKOUT: [['boxQuality', 'Quality'], ['boxWindowDays', 'Days'], ['boxWidthPct', 'Width'], ['boxBreakoutDistanceAtr', 'Breakout ATR']],
  PULLBACK_RESUME: [['pullbackDepthAtr', 'Pullback ATR'], ['reclaimDistanceAtr', 'Reclaim ATR'], ['trendScore', 'Trend'], ['rsScore', 'RS'], ['entryType', 'Entry'], ['entryScore', 'Entry Score']],
  MEAN_REVERSION: [['rsi14', 'RSI14'], ['distanceFromMa20Atr', 'MA20 / ATR'], ['return3D', '3D'], ['return5D', '5D'], ['closeLocationValue', 'CLV'], ['trendScore', 'Trend'], ['ma20Slope', 'MA20 slope'], ['state', 'State'], ['fragilityScore', 'Fragility']],
};
function context(event: StudyEvent) {
  return contextKeys[event.strategy].map(([key, label]) => {
    const raw = event.context[key];
    const formatted = raw == null ? '—' : typeof raw === 'string' ? raw : ['boxWidthPct', 'return3D', 'return5D', 'ma20Slope'].includes(key) ? pct(raw) : raw.toFixed(2);
    return `${label}: ${formatted}`;
  }).join(' · ');
}
async function exportSummary() {
  try {
    await exportExcel(`策略对比_${props.market}_${applied.value.start}_${applied.value.end}.xlsx`, '策略汇总',
      columns.map(column => ({ label: column.label, format: column.key === 'eventCount' ? '0' : column.key === 'strategy' ? undefined : '0.0%' })),
      sorted.value.map(group => columns.map(column => value(group, column.key))));
  } catch { toast.error('Excel 导出失败，请重试'); }
}
</script>

<template>
  <Card data-testid="trend-event-study">
    <CardHeader><CardTitle>Official Event Study</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <p class="text-sm text-muted-foreground">
        T-close forward return 为信号日收盘至精确交易日收盘的事后研究指标，不代表能按 T 收盘价真实成交。样本可能重叠，不是组合回测。
      </p>
      <div class="flex flex-wrap items-center gap-3">
        <span>{{ market }}</span>
        <span>时间范围</span>
        <Button
          v-for="days in [30, 60, 90, 180]"
          :key="days"
          :variant="range === days ? 'secondary' : 'outline'"
          :aria-pressed="range === days"
          @click="preset(days)"
        >
          {{ days }}D
        </Button>
        <Button
          :variant="range === 'custom' ? 'secondary' : 'outline'"
          @click="preset('custom')"
        >
          自定义
        </Button>
        <template v-if="range === 'custom'">
          <AppDatePicker
            v-model="start"
            label="开始日期"
            :max="endDate"
            :clearable="false"
          />
          <AppDatePicker
            v-model="end"
            label="结束日期"
            :min="start"
            :max="endDate"
            :clearable="false"
          />
        </template>
        <span class="text-xs text-muted-foreground">{{ start }} — {{ end }}</span>
        <label>Regime <select
          v-model="regime"
          aria-label="研究市场环境"
          class="rounded border bg-background p-2"
        ><option
          v-for="item in ['ALL', 'RISK_ON', 'NEUTRAL', 'RISK_OFF']"
          :key="item"
          :value="item"
        >{{ item }}</option></select></label>
        <Button
          :disabled="invalidRange || loading"
          data-testid="study-query"
          @click="query"
        >
          查询
        </Button>
        <Button
          variant="outline"
          :disabled="!groups.length || loading"
          @click="exportSummary"
        >
          导出汇总
        </Button>
      </div>
      <p
        v-if="invalidRange"
        role="alert"
      >
        请选择有效日期范围（不超过730天，且不晚于所选 Official 日期）。
      </p>
      <p
        v-if="loading"
        role="status"
      >
        策略统计加载中...
      </p>
      <AppApiErrorAlert
        v-if="error"
        :error="error"
      />
      <div
        v-if="result"
        class="text-xs text-muted-foreground"
        data-testid="study-coverage"
      >
        已查询 {{ applied.start }} — {{ applied.end }} · {{ applied.regime }} · 正式快照 {{ result.snapshotDates.length }} 日 · 缺少快照 {{ result.missingSnapshotDates.length }} 日 · Benchmark {{ result.benchmark }} · Box 特征 {{ pct(result.boxFeatureCoverage.featureCoverage) }} · MR 特征 {{ pct(result.mrFeatureCoverage.featureCoverage) }}
        <p>Box 连续完整自 {{ result.boxFeatureCoverage.continuousCompleteSince ?? '—' }} · MR 连续完整自 {{ result.mrFeatureCoverage.continuousCompleteSince ?? '—' }}</p>
      </div>
      <p
        v-if="groups.some(group => group.status === 'insufficient_feature_history')"
        class="rounded border p-3 text-sm"
        role="status"
      >
        insufficient_feature_history：部分历史特征或快照缺失，以下仅为已覆盖样本的描述统计，不能据此比较策略优劣。请先完成历史重算。
      </p>
      <Table data-testid="study-aggregates">
        <TableHeader>
          <TableRow>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              :active="sortKey === column.key"
              :direction="direction"
              @sort="toggleSort(column.key)"
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="group in sorted"
            :key="group.strategy"
            class="cursor-pointer"
            tabindex="0"
            :aria-label="`查看${labels[group.strategy]}样本`"
            data-testid="study-strategy-row"
            @click="choose(group.strategy)"
            @keydown.enter="choose(group.strategy)"
          >
            <TableCell
              v-for="column in columns"
              :key="column.key"
              class="whitespace-nowrap tabular-nums"
            >
              {{ column.key === 'strategy' || column.key === 'eventCount' ? value(group, column.key) : pct(value(group, column.key) as number | null) }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <section
        v-if="selected"
        class="space-y-3"
        data-testid="study-drilldown"
      >
        <h3 class="font-semibold">
          {{ labels[selected] }} · 事件样本 {{ page?.eventCount ?? '—' }}
        </h3>
        <Table v-if="chosenGroup">
          <TableHeader>
            <TableRow>
              <th
                v-for="label in ['周期', '可评价 N', '未到期', '缺行情', '平均收益', '中位收益', '胜率', '超额 N', '平均超额', '中位超额', '超额胜率']"
                :key="label"
                class="p-2 text-left text-xs"
              >
                {{ label }}
              </th>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="h in chosenGroup.horizons"
              :key="h.days"
            >
              <TableCell>{{ h.days }}D</TableCell><TableCell>{{ h.maturedCount }}</TableCell><TableCell>{{ h.pendingCount }}</TableCell><TableCell>{{ h.missingCount }}</TableCell><TableCell>{{ pct(h.meanReturn) }}</TableCell><TableCell>{{ pct(h.medianReturn) }}</TableCell><TableCell>{{ pct(h.winRate) }}</TableCell><TableCell>{{ h.excessMaturedCount }}</TableCell><TableCell>{{ pct(h.meanExcessReturn) }}</TableCell><TableCell>{{ pct(h.medianExcessReturn) }}</TableCell><TableCell>{{ pct(h.excessWinRate) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <p
          v-if="chosenGroup"
          class="text-xs text-muted-foreground"
        >
          完整20日路径 N={{ chosenGroup.excursionCount }} · MFE 中位数 {{ pct(chosenGroup.mfe20.median) }} · MAE 中位数 {{ pct(chosenGroup.mae20.median) }}
        </p>
        <p
          v-if="eventsLoading"
          role="status"
        >
          事件样本加载中...
        </p>
        <AppApiErrorAlert
          v-if="eventsError"
          :error="eventsError"
        />
        <Table data-testid="study-events">
          <TableHeader>
            <TableRow>
              <th
                v-for="label in ['Date', '股票', 'Regime', 'Signal Price', '5D', '10D', '20D', 'Excess 5D', 'Excess 10D', 'Excess 20D', 'MFE20', 'MAE20', '当日快照上下文']"
                :key="label"
                class="whitespace-nowrap p-2 text-left text-xs"
              >
                {{ label }}
              </th>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="event in page?.events ?? []"
              :key="`${event.tradeDate}-${event.code}-${event.strategy}`"
              data-testid="study-event-row"
            >
              <TableCell class="whitespace-nowrap">
                {{ event.tradeDate }}
              </TableCell><TableCell>{{ event.name ?? '—' }}<span class="block text-xs">{{ event.code }}</span></TableCell><TableCell>{{ event.regime }}</TableCell><TableCell>{{ event.signalPrice.toFixed(2) }}</TableCell>
              <TableCell
                v-for="days in [5, 10, 20]"
                :key="days"
              >
                {{ point(event, days) }}
              </TableCell><TableCell
                v-for="days in [5, 10, 20]"
                :key="`excess-${days}`"
              >
                {{ point(event, days, true) }}
              </TableCell>
              <TableCell>{{ event.excursionStatus === 'available' ? pct(event.mfe20) : statusText(event.excursionStatus) }}</TableCell><TableCell>{{ event.excursionStatus === 'available' ? pct(event.mae20) : statusText(event.excursionStatus) }}</TableCell>
              <TableCell class="min-w-80 text-xs">
                {{ context(event) }}<span
                  v-if="event.missingDates.length"
                  class="block"
                >路径缺失 {{ event.missingDates.join(', ') }}</span>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div class="flex items-center gap-3">
          <Button
            variant="outline"
            :disabled="eventsLoading || offset === 0"
            @click="turnPage(Math.max(0, offset - 100))"
          >
            上一页
          </Button><span>第 {{ Math.floor(offset / 100) + 1 }} 页</span><Button
            variant="outline"
            :disabled="eventsLoading || !page || offset + 100 >= page.eventCount"
            @click="turnPage(offset + 100)"
          >
            下一页
          </Button>
        </div>
      </section>
    </CardContent>
  </Card>
</template>
