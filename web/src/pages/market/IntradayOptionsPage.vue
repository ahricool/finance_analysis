<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { fetchIntradayOptions, type IntradayOptionRow, type IntradayOptionsSnapshot, type TrendDirection } from '@/api/intradayOptions';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useTableSort } from '@/composables/useTableSort';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { clock, dataLabels, directionOrder, directions, fmt, pct, stageOrder, stages, tone, usable } from '@/components/intraday-options/labels';

const TrendPanel = defineAsyncComponent(() => import('@/components/intraday-options/TrendPanel.vue'));
const snapshot = shallowRef<IntradayOptionsSnapshot | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const search = ref('');
const filter = ref<'all' | TrendDirection>('all');
const expanded = ref<string | null>(null);
const sortSnapshot = shallowRef<IntradayOptionRow[]>([]);
const now = useCurrentTime(1000);
const disconnected = computed(() => !!error.value || (!!snapshot.value && now.value.getTime() - Date.parse(snapshot.value.generatedAt) > 20_000));
const columns = [
  { key: 'symbol', label: '标的', description: '按代码排序；名称与代码均可搜索。' },
  { key: 'lastPrice', label: '最新价' }, { key: 'changePct', label: '当日涨跌幅', description: '相对昨收；不参与当前趋势评分。' },
  ...[15, 30, 60].map(n => ({ key: `w${n}`, label: `${n}分钟`, description: '按窗口质量分排序；箭头表示方向，第二行是该窗口涨跌幅。' })),
  { key: 'direction', label: '当前方向' }, { key: 'score', label: '趋势机会分', description: '0–100规则分，不是盈利概率；开盘满60分钟后显示；缺线或延迟仍展示并标注。' },
  { key: 'state', label: '当前状态', description: '趋势质量与进场位置分开：高分仍可能处于短线延伸。' },
];
const filters: Array<{ key: typeof filter.value; label: string }> = [
  { key: 'all', label: '全部' }, { key: 'bullish', label: '偏多' }, { key: 'bearish', label: '偏空' }, { key: 'conflict', label: '方向分歧' },
];
const matches = computed(() => sortSnapshot.value.filter(row => {
  const term = search.value.trim().toLowerCase();
  return (!term || `${row.symbol} ${row.name ?? ''}`.toLowerCase().includes(term))
    && (filter.value === 'all' || (usable(row) && row.result?.direction === filter.value));
}));
function sortValue(row: IntradayOptionRow, key: string): unknown {
  if (key === 'symbol') return row.symbol;
  if (key === 'lastPrice' || key === 'changePct') return row[key];
  if (!usable(row)) return null;
  if (key.startsWith('w')) return row.result?.windows.find(w => w.minutes === Number(key.slice(1)))?.score;
  if (key === 'direction') return row.result?.direction ? directionOrder[row.result.direction] : null;
  if (key === 'state') return row.result?.state ? stageOrder[row.result.state] : null;
  return row.result?.score;
}
const table = useTableSort(() => matches.value, sortValue);
table.sortKey = 'score'; table.direction = 'desc';
const liveBySymbol = computed(() => new Map(snapshot.value?.items.map(row => [row.symbol, row]) ?? []));
const rows = computed(() => table.sorted.map(row => liveBySymbol.value.get(row.symbol) ?? row));
function refreshOrder() { sortSnapshot.value = [...(snapshot.value?.items ?? [])]; }
function toggleSort(key: string) { refreshOrder(); table.toggle(key); }
watch([filter, search], () => { refreshOrder(); expanded.value = null; });
function windowOf(row: IntradayOptionRow, minutes: number) { return row.result?.windows.find(w => w.minutes === minutes); }
function valid(row: IntradayOptionRow) { return usable(row); }
function rowDirection(row: IntradayOptionRow) { return valid(row) && row.result?.direction ? directions[row.result.direction] : '—'; }
function arrow(value: number | null | undefined) { return value === 1 ? '↑' : value === -1 ? '↓' : '→'; }
function toggleRow(symbol: string) { expanded.value = expanded.value === symbol ? null : symbol; }
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | null = null;
let stopped = false;
async function load() {
  if (controller || stopped) return;
  const request = new AbortController(); controller = request;
  try {
    const result = await fetchIntradayOptions(request.signal);
    if (stopped) return;
    const reset = !snapshot.value || snapshot.value.tradingDate !== result.tradingDate;
    snapshot.value = result; error.value = null;
    if (reset) { refreshOrder(); expanded.value = null; }
  } catch (reason) { if (!stopped && !request.signal.aborted) error.value = getParsedApiError(reason); }
  finally { controller = null; loading.value = false; if (!stopped) timer = setTimeout(() => { void load(); }, 5000); }
}
void load();
onBeforeUnmount(() => { stopped = true; controller?.abort(); clearTimeout(timer); });
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="intraday-options-page"
  >
    <PageHeader
      title="日内期权交易"
      en="Intraday Options"
      description="固定30个标的 · 按股票/ETF的分钟走势筛选顺势观察机会；分数不是盈利概率。"
    />
    <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
      <div class="flex flex-wrap gap-3 text-muted-foreground">
        <span>交易日期 {{ snapshot?.tradingDate ?? '—' }}</span>
        <span>{{ snapshot ? { open: '交易中', preopen: '未开盘 · 展示上一交易日', closed: '已收盘 · 保留最后结果' }[snapshot.marketStatus] : '连接中' }}</span>
        <span>更新 {{ clock(snapshot?.generatedAt) }}（纽约）</span>
        <span
          v-if="disconnected"
          class="text-destructive"
        >连接中断或响应过期，保留上次评分，仅供参考</span>
      </div>
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
      数值持续更新，排序及筛选名单保持不动；点击表头、切换筛选或“更新排序”时重新排列。三个窗口完整前可点击单窗口表头观察。
    </p>
    <div class="overflow-hidden rounded-lg border">
      <Table>
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
              :colspan="9"
              class="py-12 text-center text-muted-foreground"
            >
              {{ loading ? '加载固定观察池…' : error ? '行情连接失败，请等待重试。' : '没有符合筛选条件的标的。' }}
            </TableCell>
          </TableRow>
          <template
            v-for="row in rows"
            :key="row.symbol"
          >
            <TableRow
              class="cursor-pointer"
              :data-testid="`options-row-${row.symbol}`"
              :data-state="expanded === row.symbol ? 'selected' : undefined"
              @click="toggleRow(row.symbol)"
            >
              <TableCell class="max-w-48 py-2">
                <button
                  class="text-left font-medium hover:underline"
                  :aria-expanded="expanded === row.symbol"
                  :aria-label="`展开${row.symbol}分钟图`"
                  @click.stop="toggleRow(row.symbol)"
                >
                  {{ row.symbol.replace('.US', '') }}
                </button>
                <p class="max-w-44 truncate text-xs text-muted-foreground">
                  {{ row.name ?? '主数据未识别' }}
                </p>
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
                {{ fmt(row.lastPrice, 2) }}<p
                  v-if="row.quoteStatus !== 'ready'"
                  class="text-xs text-muted-foreground"
                >
                  {{ { missing: '暂无报价', delayed: '报价延迟', invalid_time: '报价时间异常' }[row.quoteStatus] }}
                </p>
              </TableCell>
              <TableCell
                class="tabular-nums"
                :class="tone(row.changePct)"
              >
                {{ pct(row.changePct) }}
              </TableCell>
              <TableCell
                v-for="n in [15, 30, 60]"
                :key="n"
                class="whitespace-nowrap tabular-nums"
              >
                <template v-if="valid(row) && windowOf(row, n)?.score != null">
                  <span :class="tone(windowOf(row, n)?.direction)">{{ arrow(windowOf(row, n)?.direction) }} {{ fmt(windowOf(row, n)?.score, 0) }}分</span>
                  <p class="text-xs text-muted-foreground">
                    {{ pct(windowOf(row, n)?.returnPct) }}
                  </p>
                  <p
                    v-if="windowOf(row, n)?.dataStatus === 'gap'"
                    class="text-xs text-amber-600 dark:text-amber-400"
                  >
                    缺{{ windowOf(row, n)?.missingBars ?? '部分' }}根 · 参考分
                  </p>
                </template>
                <template v-else>
                  —<p class="text-xs text-muted-foreground">
                    {{ windowOf(row, n)?.dataStatus === 'gap' ? '分钟缺失' : valid(row) ? '预热中' : '等待有效数据' }}
                  </p>
                </template>
              </TableCell>
              <TableCell
                class="whitespace-nowrap"
                :class="valid(row) ? tone(row.result?.direction === 'bullish' ? 1 : row.result?.direction === 'bearish' ? -1 : 0) : ''"
              >
                {{ rowDirection(row) }}
              </TableCell>
              <TableCell
                class="text-lg font-semibold tabular-nums"
                data-testid="opportunity-score"
              >
                {{ valid(row) ? fmt(row.result?.score, 0) : '—' }}
                <p
                  v-if="row.result && (disconnected || row.dataStatus === 'delayed' || row.result.windows.some(w => w.dataStatus === 'gap'))"
                  class="text-xs font-normal text-amber-600 dark:text-amber-400"
                >
                  参考分 · 截至 {{ clock(row.result.asOf) }}
                </p>
              </TableCell>
              <TableCell class="whitespace-nowrap text-sm">
                {{ valid(row) && row.result?.state ? stages[row.result.state] : '—' }}
              </TableCell>
            </TableRow>
            <TableRow v-if="expanded === row.symbol">
              <TableCell
                :colspan="9"
                class="p-3"
              >
                <TrendPanel
                  :symbol="row.symbol"
                  :result="row.result"
                  :stale="disconnected || row.dataStatus === 'delayed' || !valid(row)"
                />
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>
    </div>
    <p class="text-xs text-muted-foreground">
      {{ rows.length }} / {{ snapshot?.items.length ?? 30 }} 个标的 · 仅正常交易时段评分 · 不选择期权合约，不自动下单 · 评分只保留最新缓存，不保存历史
    </p>
  </div>
</template>
