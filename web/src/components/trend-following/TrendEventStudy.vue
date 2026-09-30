<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { exportExcel } from '@/utils/excelExport';
import { toast } from 'vue-sonner';
import type { EventStudyResponse, StrategyKey, StudyGroup, StudyEvent, StudyRegime, TrendMarket, EvaluationStatus } from '@/types/trendFollowing';

const props = defineProps<{ market: TrendMarket; endDate: string }>();
const end = ref(props.endDate || new Date().toISOString().slice(0, 10));
const initialStart = new Date(`${end.value}T00:00:00Z`);
initialStart.setUTCDate(initialStart.getUTCDate() - 180);
const start = ref(initialStart.toISOString().slice(0, 10));
const regime = ref<StudyRegime>('ALL');
const selected = ref<StrategyKey | null>(null);
const offset = ref(0);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const result = shallowRef<EventStudyResponse | null>(null);
const groups = shallowRef<StudyGroup[]>([]);
const labels: Record<StrategyKey, string> = { TREND_FOLLOWING: '趋势', BOX_BREAKOUT: '箱体突破', PULLBACK_RESUME: '趋势回调', MEAN_REVERSION: '超跌反弹' };
let controller: AbortController | undefined;
watch(() => props.endDate, value => { if (value) end.value = value; });
watch([() => props.market, start, end, regime], () => { selected.value = null; offset.value = 0; groups.value = []; });
watch([() => props.market, start, end, regime, selected, offset], async () => {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  error.value = null;
  result.value = null;
  if (!start.value || !end.value || start.value > end.value) { loading.value = false; return; }
  loading.value = true;
  try {
    const response = await trendFollowingApi.eventStudy(props.market, start.value, end.value, regime.value, selected.value ?? 'ALL', offset.value, request.signal);
    if (request.signal.aborted) return;
    result.value = response;
    if (!selected.value) groups.value = response.groups.filter(group => group.regime === regime.value);
  } catch (e) {
    if (!request.signal.aborted) error.value = getParsedApiError(e);
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}, { immediate: true });
onBeforeUnmount(() => controller?.abort());

const columns = [
  { key: 'strategy', label: '策略' }, { key: 'eventCount', label: 'N' },
  ...[5, 10, 20].flatMap(days => [{ key: `win${days}`, label: `${days}D 胜率` }, { key: `excess${days}`, label: `${days}D 平均超额` }]),
  { key: 'mfe20', label: '平均 MFE20' }, { key: 'mae20', label: '平均 MAE20' },
  { key: 'coverage', label: '特征覆盖' },
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
function choose(strategy: StrategyKey) { selected.value = strategy; offset.value = 0; }
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
    await exportExcel(`策略对比_${props.market}_${start.value}_${end.value}.xlsx`, '策略汇总',
      columns.map(column => ({ label: column.label, format: column.key === 'eventCount' ? '0' : column.key === 'strategy' ? undefined : '0.0%' })),
      sorted.value.map(group => columns.map(column => value(group, column.key))));
  } catch { toast.error('Excel 导出失败，请重试'); }
}
</script>

<template>
  <Card data-testid="trend-event-study">
    <CardHeader><CardTitle>策略对比 · Official Event Study</CardTitle></CardHeader>
    <CardContent class="space-y-4">
      <p class="text-sm text-muted-foreground">
        T-close forward return 为信号日收盘至精确交易日收盘的事后研究指标，不代表能按 T 收盘价真实成交。样本可能重叠，不是组合回测。
      </p>
      <div class="flex flex-wrap items-center gap-3">
        <span>{{ market }}</span>
        <label>开始日期 <input
          v-model="start"
          type="date"
          aria-label="研究开始日期"
          class="rounded border bg-background p-2"
        ></label>
        <label>结束日期 <input
          v-model="end"
          type="date"
          aria-label="研究结束日期"
          class="rounded border bg-background p-2"
        ></label>
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
          variant="outline"
          :disabled="!groups.length || loading"
          @click="exportSummary"
        >
          导出汇总
        </Button>
      </div>
      <p
        v-if="start > end"
        role="alert"
      >
        开始日期不能晚于结束日期。
      </p>
      <p
        v-if="loading"
        role="status"
      >
        正在评价正式历史事件…
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
        正式快照 {{ result.snapshotDates.length }} 日 · 缺少快照 {{ result.missingSnapshotDates.length }} 日 · Benchmark {{ result.benchmark }} · Box 特征 {{ pct(result.boxFeatureCoverage.featureCoverage) }} · MR 特征 {{ pct(result.mrFeatureCoverage.featureCoverage) }}
        <p>Box 最早完整日期 {{ result.boxFeatureCoverage.earliestCompleteDate ?? '—' }} · MR 最早完整日期 {{ result.mrFeatureCoverage.earliestCompleteDate ?? '—' }}</p>
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
          {{ labels[selected] }} · 事件样本 {{ result?.eventCount ?? '—' }}
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
              v-for="event in result?.events ?? []"
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
            :disabled="loading || offset === 0"
            @click="offset = Math.max(0, offset - 100)"
          >
            上一页
          </Button><span>第 {{ Math.floor(offset / 100) + 1 }} 页</span><Button
            variant="outline"
            :disabled="loading || !result || offset + 100 >= result.eventCount"
            @click="offset += 100"
          >
            下一页
          </Button>
        </div>
      </section>
    </CardContent>
  </Card>
</template>
