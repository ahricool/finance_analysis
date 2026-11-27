<script setup lang="ts">
import StockDailyChart from '@/components/market-data/instrument-table/StockDailyChart.vue';
import StockLink from '@/components/stocks/StockLink.vue';
import InstrumentTable from '@/components/market-data/instrument-table/InstrumentTable.vue';
import InstrumentRow from '@/components/market-data/instrument-table/InstrumentRow.vue';
import TrendWindowCell from '@/components/market-data/TrendWindowCell.vue';
import TrendDirectionCell from '@/components/market-data/TrendDirectionCell.vue';
import { computed, defineAsyncComponent, ref, shallowRef, watch } from 'vue';
import { type IntradayOptionRow, type IntradayOptionsSnapshot, type TrendDirection } from '@/api/intradayOptions';
import { type ParsedApiError } from '@/api/error';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Button } from '@/components/ui/button';
import { TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useTableSort } from '@/composables/useTableSort';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { clock, entryScore, entryLabel, entryBranch, entryReason, rowDirectionValue, opportunityKinds, dataLabels, directionOrder, directions, fmt, pct, stageOrder, stages, structureName, structurePhases, tone, usable } from '@/components/intraday-options/labels';

import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import SimulationPanel from '@/components/intraday-options/SimulationPanel.vue';
import IndustryMap from '@/components/intraday-options/IndustryMap.vue';

const TrendPanel = defineAsyncComponent(() => import('@/components/intraday-options/TrendPanel.vue'));
const snapshot = shallowRef<IntradayOptionsSnapshot | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const search = ref('');
const filter = ref<'all' | TrendDirection>('all');
const sortSnapshot = shallowRef<IntradayOptionRow[]>([]);
const now = useCurrentTime(1000);
const connectionLost = computed(() => !['connected', 'sse'].includes(stream.status.value) || !!error.value);
const snapshotExpired = computed(() => {
  if (!snapshot.value) return false;
  const age = now.value.getTime() - Date.parse(snapshot.value.generatedAt);
  return !Number.isFinite(age) || age > 20_000;
});
const disconnected = computed(() => connectionLost.value || snapshotExpired.value);
const columns = [
  { key: 'symbol', label: '标的', description: '按代码排序；名称与代码均可搜索。' },
  { key: 'changePct', label: '最新价 / 涨跌幅', description: '按当日涨跌幅排序；涨跌幅相对昨收，不参与趋势评分。' },
  { key: 'opportunity', label: '日内机会', description: '按有效确认分支质量排序；形成中、延伸、失效、缺线或延迟均不列入有效机会。' },
  { key: 'score', label: '趋势质量分', description: '0–100规则分，不是盈利概率；开盘不足完整窗口或缺线时也按可用K线计算并标注参考分。' },
  { key: 'direction', label: '当前方向', description: '有有效机会时与榜单分支方向一致；无有效机会时显示趋势参考方向。' },
  ...[5, 15, 30, 60].map(n => ({ key: `w${n}`, label: `${n}分钟`, description: '按窗口质量分排序；箭头表示方向，第二行是该窗口涨跌幅。' })),
  { key: 'structure', label: '短线结构', description: '最近15分钟完整后判断；15–30分钟结构、5分钟变化，最多60分钟背景。内部空缺按前收盘补平K并标注；进场确认仍需真实K。' },
  { key: 'state', label: '当前状态', description: '趋势质量与进场位置分开：高分仍可能处于短线延伸。' },
];
const filters: Array<{ key: typeof filter.value; label: string }> = [
  { key: 'all', label: '全部' }, { key: 'bullish', label: '偏多' }, { key: 'bearish', label: '偏空' }, { key: 'conflict', label: '方向分歧' },
];
const matches = computed(() => sortSnapshot.value.filter(row => {
  const term = search.value.trim().toLowerCase();
  return (!term || `${row.symbol} ${row.name ?? ''}`.toLowerCase().includes(term))
    && (filter.value === 'all' || (usable(row) && rowDirectionValue(row) === filter.value));
}));
function sortValue(row: IntradayOptionRow, key: string): unknown {
  if (key === 'symbol') return row.symbol;
  if (key === 'changePct') return row.changePct;
  if (key === 'opportunity') return entryScore(row);
  if (!usable(row)) return null;
  if (key === 'structure') return row.result?.structure ? structureName(row.result.structure) : null;
  if (key.startsWith('w')) return row.result?.windows.find(w => w.minutes === Number(key.slice(1)))?.score;
  if (key === 'direction') return rowDirectionValue(row) ? directionOrder[rowDirectionValue(row)!] : null;
  if (key === 'state') return row.result?.state ? stageOrder[row.result.state] : null;
  return row.result?.score;
}
const table = useTableSort(() => matches.value, sortValue);
table.sortKey = 'opportunity'; table.direction = 'desc';
const liveBySymbol = computed(() => new Map(snapshot.value?.items.map(row => [row.symbol, row]) ?? []));
const rows = computed(() => table.sorted.map(row => liveBySymbol.value.get(row.symbol) ?? row));
function refreshOrder() { sortSnapshot.value = [...(snapshot.value?.items ?? [])]; }
function toggleSort(key: string) { refreshOrder(); table.toggle(key); }
watch([filter, search], () => { refreshOrder(); });
function windowOf(row: IntradayOptionRow, minutes: number) { return row.result?.windows.find(w => w.minutes === minutes); }
function valid(row: IntradayOptionRow) { return usable(row); }
const stream = useRealtimeQuotes({ scope: 'intraday-options', market: 'US' });
watch(stream.intradayOptions, result => {
  if (!result) return;
  const previous = snapshot.value;
  const reset = !previous || previous.tradingDate !== result.tradingDate || previous.version !== result.version
    || previous.items.length !== result.items.length
    || (previous.items !== result.items && previous.items.some((row, i) => row.symbol !== result.items[i]?.symbol));
  snapshot.value = result; error.value = null; loading.value = false;
  if (reset) { refreshOrder(); }
});
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="intraday-options-page"
  >
    <PageHeader
      title="日内期权交易"
      en="Intraday Options"
      description="QQQ（纳指100）成分股 + SPY/QQQ 观察池 · 趋势质量与日内入场机会分开观察；分数不是盈利概率。"
    />
    <SimulationPanel
      v-if="snapshot"
      :snapshot="snapshot"
      :disconnected="connectionLost"
      :snapshot-expired="snapshotExpired"
    />
    <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
      <div class="flex flex-wrap gap-3 text-muted-foreground">
        <span>交易日期 {{ snapshot?.tradingDate ?? '—' }}</span>
        <span>{{ snapshot ? { open: '交易中', preopen: '未开盘 · 展示上一交易日', closed: '已收盘 · 保留最后结果' }[snapshot.marketStatus] : '连接中' }}</span>
        <span>更新 {{ clock(snapshot?.generatedAt) }}（纽约）</span>
        <span
          v-if="disconnected"
          class="text-destructive"
        >{{ connectionLost ? '连接中断，保留上次评分，仅供参考' : '快照更新延迟，保留上次评分，仅供参考' }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <a
          v-if="snapshot?.items.length"
          href="#intraday-industry-map"
          class="text-sm text-primary underline-offset-4 hover:underline"
        >查看行业图</a>
        <Button
          variant="outline"
          size="sm"
          :disabled="loading || disconnected"
          data-testid="options-refresh-order"
          @click="refreshOrder"
        >
          更新排序
        </Button>
      </div>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div
        class="flex flex-wrap gap-1"
        role="group"
        aria-label="方向筛选"
      >
        <Button
          v-for="item in filters"
          :key="item.key"
          size="sm"
          :variant="filter === item.key ? 'secondary' : 'ghost'"
          :aria-pressed="filter === item.key"
          @click="filter = item.key"
        >
          {{ item.label }}
        </Button>
      </div>
      <FieldInput
        v-model="search"
        class="w-full sm:w-64"
        placeholder="搜索名称或代码"
        aria-label="搜索标的"
      />
    </div>
    <p class="text-xs text-muted-foreground">
      数值持续更新，排序及筛选名单保持不动；点击表头、切换筛选或“更新排序”时重新排列。开盘不足完整窗口或分钟缺失时按可用K线计算参考分，并标注缺失；少于2根有效K线时等待数据。日内机会需完整形态背景与相邻闭合K确认，默认仅按有效机会分排序，其余保持观察池顺序。
    </p>
    <div class="overflow-hidden rounded-lg border">
      <InstrumentTable data-testid="options-market-table">
        <TableHeader>
          <TableRow>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              :description="column.description"
              :active="table.sortKey === column.key"
              :direction="table.direction"
              @sort="toggleSort(column.key)"
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="!rows.length">
            <TableCell
              :colspan="columns.length"
              class="py-12 text-center text-muted-foreground"
            >
              {{ loading ? '加载观察池…' : error ? '行情连接失败，请等待重试。' : '没有符合筛选条件的标的。' }}
            </TableCell>
          </TableRow>
          <template
            v-for="row in rows"
            :key="row.symbol"
          >
            <InstrumentRow
              :symbol="row.symbol"
              market="US"
              class="cursor-pointer"
              :data-testid="`options-row-${row.symbol}`"
            >
              <TableCell class="max-w-48 py-2">
                <StockLink
                  :code="row.symbol"
                  :name="row.name"
                  market="US"
                />
                <p
                  v-if="row.dataStatus !== 'ready'"
                  class="text-xs text-amber-600 dark:text-amber-400"
                >
                  {{ dataLabels[row.dataStatus] }}
                </p>
                <p
                  v-for="issue in row.issues.filter(i => !i.startsWith('主数据'))"
                  :key="issue"
                  class="text-xs text-amber-600 dark:text-amber-400"
                >
                  {{ issue }}
                </p>
              </TableCell>
              <TableCell class="tabular-nums">
                {{ fmt(row.lastPrice, 2) }}
                <p
                  class="text-xs"
                  :class="tone(row.changePct)"
                >
                  {{ pct(row.changePct) }}
                </p>
                <p
                  v-if="row.quoteStatus !== 'ready'"
                  class="text-xs text-muted-foreground"
                >
                  {{ { missing: '暂无报价', delayed: '报价延迟', invalid_time: '报价时间异常' }[row.quoteStatus] }}
                </p>
              </TableCell>
              <TableCell
                class="whitespace-nowrap text-sm"
                data-testid="opportunity-score"
              >
                <p class="font-semibold tabular-nums">
                  {{ disconnected ? '—' : fmt(entryScore(row), 0) }}
                  <span v-if="!disconnected && entryScore(row) != null">分</span>
                </p>
                <p>{{ entryLabel(row, disconnected) }}</p>
                <p
                  v-if="entryBranch(row)"
                  class="text-xs text-muted-foreground"
                >
                  {{ opportunityKinds[entryBranch(row)!.kind] }} · {{ directions[entryBranch(row)!.direction] }}
                </p>
                <p
                  v-if="!disconnected && entryReason(row)"
                  class="max-w-64 whitespace-normal text-xs text-muted-foreground"
                  data-testid="opportunity-reason"
                >
                  {{ entryReason(row) }}
                </p>
                <p
                  v-if="row.result?.opportunities && (!row.opportunityEligible || disconnected)"
                  class="text-xs text-muted-foreground"
                >
                  截至 {{ clock(row.result.opportunities.asOf) }}
                </p>
              </TableCell>
              <TableCell
                class="text-lg font-semibold tabular-nums"
                data-testid="trend-quality-score"
              >
                {{ valid(row) ? fmt(row.result?.score, 0) : '—' }}
                <p
                  v-if="row.result && (disconnected || row.dataStatus === 'delayed' || row.result.windows.some(w => w.dataStatus !== 'ready'))"
                  class="text-xs font-normal text-amber-600 dark:text-amber-400"
                >
                  参考分 · 截至 {{ clock(row.result.asOf) }}
                </p>
              </TableCell>
              <TrendDirectionCell :direction="valid(row) ? rowDirectionValue(row) : null" />

              <TrendWindowCell
                v-for="n in [5, 15, 30, 60]"
                :key="n"
                :window="valid(row) ? windowOf(row, n) : undefined"
              />

              <TableCell
                class="whitespace-nowrap text-sm"
                data-testid="intraday-structure"
              >
                <template v-if="valid(row) && row.result?.structure">
                  <p class="font-medium">
                    {{ structureName(row.result.structure) }}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    {{ structurePhases[row.result.structure.phase] }} · {{ directions[row.result.structure.background] }}背景
                  </p>
                  <p
                    v-if="row.result.structure.reference"
                    class="text-xs text-amber-600 dark:text-amber-400"
                  >
                    参考结构 · 缺{{ row.result.structure.missingBars }}根
                  </p>
                  <p
                    v-if="disconnected || row.dataStatus === 'delayed'"
                    class="text-xs text-amber-600 dark:text-amber-400"
                  >
                    延迟 · 截至 {{ clock(row.result.structure.asOf) }}
                  </p>
                </template>
                <span v-else>—</span>
              </TableCell>
              <TableCell class="whitespace-nowrap text-sm">
                {{ valid(row) && row.result?.state ? stages[row.result.state] : '—' }}
              </TableCell>
              <template #chart="{ period }">
                <TrendPanel
                  v-if="period === '1m'"
                  :symbol="row.symbol"
                  :simulation="snapshot?.simulation"
                  :result="row.result"
                  :stale="disconnected || snapshot?.marketStatus !== 'open' || row.dataStatus === 'delayed' || !valid(row)"
                />
                <StockDailyChart
                  v-else
                  :symbol="row.symbol"
                />
              </template>
            </InstrumentRow>
          </template>
        </TableBody>
      </InstrumentTable>
    </div>
    <p class="text-xs text-muted-foreground">
      {{ rows.length }} / {{ snapshot?.items.length ?? 0 }} 个标的 · 仅正常交易时段评分 · 不选择期权合约，不自动下单 · 趋势评分保留最新缓存；模拟交易与事件独立保存
    </p>
    <IndustryMap
      v-if="snapshot?.items.length"
      :rows="snapshot.items"
      :disconnected="disconnected"
    />
  </div>
</template>
