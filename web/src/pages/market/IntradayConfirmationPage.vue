<script setup lang="ts">
import { formatFixed, formatPercent } from '@/utils/number';
import StockLink from '@/components/stocks/StockLink.vue';
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { intradayConfirmationApi as api, type Snapshot, type Confirmation, type Market, type State, type Source } from '@/api/intradayConfirmation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import AppPagination from '@/components/app/AppPagination.vue';
import { intradayLabel } from '@/i18n/labels';
import { Activity, ArrowUpRight, Clock3, RefreshCw, Search, ShieldAlert } from 'lucide-vue-next';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const market = ref<Market>('CN');
const tradeDate = ref(''); const dates = ref<string[]>([]);
const datesLoading = ref(false); const datesError = shallowRef<ParsedApiError | null>(null);
const state = ref<State | ''>(''); const source = ref<Source | ''>('');
const result = shallowRef<Snapshot | null>(null); const selected = shallowRef<Confirmation | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false); const submitting = ref(false); const dialogOpen = ref(false); const taskId = ref('');
const search = ref(''); const page = ref(1); const currentFilter = ref('');
const filtered = computed(() => (result.value?.items ?? []).filter(row =>
  `${row.code} ${row.name}`.toLowerCase().includes(search.value.toLowerCase()) &&
  (!currentFilter.value || (row.currentStatus ?? 'LEGACY') === currentFilter.value)));
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / 15)));
const visibleRows = computed(() => filtered.value.slice((page.value - 1) * 15, page.value * 15));
watch([search, currentFilter, result], () => { page.value = 1; });
const cards = computed(() => [
  { label: '冻结候选', value: result.value?.summary.total ?? 0, note: '三个正式来源 · 去重保留', icon: Activity },
  { label: '曾经确认', value: result.value?.summary.everConfirmed ?? result.value?.summary.confirmed ?? 0, note: '首次价格固定 · 追踪后续收益', icon: ArrowUpRight },
  { label: '当前有效', value: result.value?.ruleVersion === 'intraday_v2' ? result.value.summary.active ?? 0 : '—', note: '最新评估仍满足确认条件', icon: Clock3 },
  { label: '需要关注', value: result.value?.ruleVersion === 'intraday_v2' ? result.value.summary.attention ?? 0 : '—', note: '走弱 / 失效 / 数据不足', icon: ShieldAlert },
]);
function currentClass(row: Confirmation) {
  return row.currentStatus === 'ACTIVE' ? 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' :
    ['FAILED', 'WEAKENING'].includes(row.currentStatus ?? '') ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'border-border bg-muted/40 text-muted-foreground';
}
let generation = 0; let datesGeneration = 0; let runGeneration = 0;
let controller: AbortController | undefined; let datesController: AbortController | undefined;
async function loadDates() {
  const token = ++datesGeneration;
  datesController?.abort(); datesController = new AbortController();
  datesLoading.value = true; datesError.value = null;
  try {
    const data = await api.dates(market.value, datesController.signal);
    if (token === datesGeneration) dates.value = data.dates;
  } catch (cause) { if (token === datesGeneration) datesError.value = getParsedApiError(cause); }
  finally { if (token === datesGeneration) datesLoading.value = false; }
}
function refresh() { void load(); void loadDates(); }
async function load() {
  const token = ++generation;
  controller?.abort(); controller = new AbortController();
  loading.value = true; error.value = null; result.value = null; selected.value = null; dialogOpen.value = false;
  try {
    const data = await api.read(market.value, state.value || undefined, source.value || undefined, tradeDate.value || undefined, controller.signal);
    if (token === generation) result.value = data;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function setMarket(target: Market) {
  if (target === market.value) return;
  market.value = target; tradeDate.value = ''; dates.value = [];
  ++runGeneration; taskId.value = ''; submitting.value = false;
  refresh();
}
async function run() {
  if (tradeDate.value || submitting.value) return;
  const token = ++runGeneration;
  submitting.value = true; error.value = null; taskId.value = '';
  try { const task = await api.run(market.value); if (token === runGeneration) taskId.value = task.taskId; }
  catch (cause) { if (token === runGeneration) error.value = getParsedApiError(cause); }
  finally { if (token === runGeneration) submitting.value = false; }
}
function pct(value: unknown) { return formatPercent(value, { digits: 2, fallback: '—' }); }
function num(value: unknown) { return formatFixed(value, { fallback: '—' }); }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : '—'; }
function show(row: Confirmation) { selected.value = row; dialogOpen.value = true; }
onMounted(refresh);
onBeforeUnmount(() => { ++generation; ++datesGeneration; ++runGeneration; controller?.abort(); datesController?.abort(); });
function forwardReturn(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : ''; }
function returnClass(value: unknown) { return typeof value === 'number' && value > 0 ? 'text-market-up' : typeof value === 'number' && value < 0 ? 'text-market-down' : ''; }
const detailInitialTab = ref<'overview' | 'intraday'>('intraday');
</script>

<template>
  <div
    class="min-w-0 space-y-5"
    data-testid="intraday-confirmation-page"
  >
    <PageHeader
      variant="section"
      title="盘中确认"
      en="Intraday Confirmation"
      description="跟踪昨日精选与趋势候选，用今日价格结构确认强弱。"
    >
      <template #actions>
        <ResearchMarketToggle
          :model-value="market"
          data-testid="intraday-market-switcher"
          @update:model-value="setMarket"
        />
        <Button
          variant="outline"
          :disabled="loading"
          @click="refresh"
        >
          <RefreshCw
            class="size-4"
            :class="loading ? 'animate-spin' : ''"
          />刷新快照
        </Button>
        <Button
          v-if="currentUser?.role === 'admin'"
          :disabled="submitting || !!tradeDate"
          @click="run"
        >
          运行当日确认任务
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="datesError"
      class="space-y-2"
    >
      <AppApiErrorAlert :error="datesError" /><Button
        variant="outline"
        @click="loadDates"
      >
        重试历史日期
      </Button>
    </div>
    <p
      v-if="taskId"
      class="rounded-lg border bg-muted/30 p-3 text-sm"
    >
      任务已提交：{{ taskId }}，请在任务中心查看。运行后刷新快照。
    </p>

    <section class="overflow-hidden rounded-xl border bg-card">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b bg-muted/25 px-5 py-3">
        <div class="flex items-center gap-2 text-sm font-medium">
          <span class="size-2 rounded-full bg-sky-500" />{{ tradeDate ? `历史快照 ${tradeDate}` : '当日观察' }}<Badge variant="outline">
            {{ result?.status === 'not_frozen' ? '等待冻结' : result?.ruleVersion === 'intraday_v2' ? '一分钟价格结构' : result ? '历史规则' : '等待快照' }}
          </Badge>
        </div>
        <span class="text-xs text-muted-foreground">{{ result?.ruleVersion === 'intraday_v2' ? '每 5 分钟评估 · 无自动交易' : '按保存时的规则展示' }}</span>
      </div>
      <div class="grid grid-cols-2 gap-px bg-border xl:grid-cols-4">
        <div
          v-for="card in cards"
          :key="card.label"
          class="space-y-3 bg-card p-5"
        >
          <div class="flex items-center justify-between text-sm text-muted-foreground">
            {{ card.label }}<component
              :is="card.icon"
              class="size-4"
            />
          </div>
          <p class="text-3xl font-semibold tracking-tight tabular-nums">
            {{ loading ? '—' : card.value }}
          </p>
          <p class="text-xs leading-relaxed text-muted-foreground">
            {{ card.note }}
          </p>
        </div>
      </div>
    </section>
    <section class="min-w-0 overflow-hidden rounded-xl border bg-card">
      <div class="flex flex-wrap items-end gap-3 border-b p-4">
        <label class="grid gap-1.5 text-xs text-muted-foreground">交易日<select
          v-model="tradeDate"
          aria-label="交易日"
          data-testid="intraday-date-selector"
          class="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
          @change="load"
        ><option value="">当日</option><option
          v-for="date in dates"
          :key="date"
          :value="date"
        >{{ date }}</option></select></label>
        <label class="grid gap-1.5 text-xs text-muted-foreground">历史状态<select
          v-model="state"
          aria-label="状态"
          class="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
          @change="load"
        ><option value="">全部状态</option><option value="CONFIRMED">曾经确认且未失效</option><option value="WAIT">等待确认</option><option value="FAILED">结构失效</option></select></label>
        <label class="grid gap-1.5 text-xs text-muted-foreground">候选来源<select
          v-model="source"
          aria-label="候选来源"
          class="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
          @change="load"
        ><option value="">全部来源</option><option value="confluence">共振精选</option><option value="trend">趋势前30</option><option value="etf">轮动前5</option><option
          v-if="result?.ruleVersion !== 'intraday_v2'"
          value="quant"
        >量化（历史）</option></select></label>
        <label class="grid gap-1.5 text-xs text-muted-foreground">当前观察<select
          v-model="currentFilter"
          aria-label="当前观察"
          class="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
        ><option value="">全部观察</option><option
          v-for="value in ['ACTIVE', 'PENDING', 'WAIT', 'WEAKENING', 'FAILED', 'RECOVERED', 'UNAVAILABLE']"
          :key="value"
          :value="value"
        >{{ intradayLabel(value) }}</option></select></label>
        <label class="relative ml-auto min-w-40 flex-1 xl:max-w-56"><Search class="absolute top-2.5 left-3 size-4 text-muted-foreground" /><input
          v-model="search"
          aria-label="搜索候选"
          placeholder="搜索名称或代码"
          class="h-9 w-full rounded-md border border-input bg-background pr-3 pl-9 text-sm"
        ></label>
      </div>
      <div
        v-if="loading"
        role="status"
        class="space-y-3 p-6"
      >
        <div
          v-for="n in 5"
          :key="n"
          class="h-12 animate-pulse rounded bg-muted"
        /><p class="text-center text-sm text-muted-foreground">
          读取已计算快照…
        </p>
      </div>
      <template v-else-if="result">
        <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs text-muted-foreground">
          <span>候选日 {{ result.candidateTradeDate ?? '—' }} → 确认日 {{ result.tradeDate }} · {{ filtered.length }} 个标的</span>
          <span>更新 {{ stamp(result.generatedAt) }}<span v-if="datesLoading"> · 读取历史日期…</span></span>
        </div>
        <div class="max-w-full overflow-x-auto">
          <Table class="min-w-[1180px] text-sm">
            <TableHeader class="bg-muted/30">
              <TableRow>
                <TableHead class="w-44 pl-4">
                  证券 / 来源
                </TableHead><TableHead>当前观察 / 历史</TableHead><TableHead class="text-right">
                  确认分
                </TableHead>
                <TableHead class="text-right">
                  最新价 / 日内
                </TableHead><TableHead class="text-right">
                  相对大盘
                </TableHead><TableHead class="text-right">
                  距全天均价
                </TableHead>
                <TableHead>追高风险</TableHead><TableHead>趋势辅助</TableHead><TableHead class="text-right">
                  量比≈
                </TableHead>
                <TableHead
                  v-for="label in ['3日收益', '5日收益', '10日收益']"
                  :key="label"
                  class="text-right"
                >
                  {{ label }}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="row in visibleRows"
                :key="row.code"
                class="cursor-pointer hover:bg-muted/40"
                tabindex="0"
                @click="detailInitialTab = 'intraday'; show(row)"
                @keydown.enter.self="detailInitialTab = 'intraday'; show(row)"
                @keydown.space.self.prevent="detailInitialTab = 'intraday'; show(row)"
              >
                <TableCell class="space-y-2 py-4 pl-4">
                  <StockLink
                    :code="row.code"
                    :name="row.name"
                    :market="market"
                    @select="detailInitialTab = 'overview'; show(row)"
                  />
                  <div class="flex flex-wrap gap-1">
                    <Badge
                      v-for="origin in row.candidateSources?.length ? row.candidateSources : [row.candidateSource]"
                      :key="origin"
                      variant="outline"
                      class="px-1.5 text-[10px] font-normal"
                    >
                      {{ intradayLabel(origin) }}
                    </Badge><Badge
                      v-if="row.instrumentType === 'ETF'"
                      variant="secondary"
                      class="text-[10px]"
                    >
                      基金
                    </Badge>
                  </div>
                </TableCell>
                <TableCell>
                  <span
                    class="inline-flex rounded-md border px-2 py-1 text-xs font-medium"
                    :class="currentClass(row)"
                  >{{ intradayLabel(row.currentStatus ?? 'LEGACY') }}</span><p class="mt-1.5 text-xs text-muted-foreground">
                    {{ row.firstConfirmedAt || row.state === 'CONFIRMED' ? '曾经确认' : intradayLabel(row.state) }}<span v-if="row.firstConfirmedAt"> · {{ stamp(row.firstConfirmedAt).split(' ').at(-1) }}</span>
                  </p>
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  <span class="text-base font-semibold">{{ row.confirmationScore == null ? '—' : row.confirmationScore.toFixed(1) }}</span><p class="text-[10px] text-muted-foreground">
                    有效权重 {{ row.availableScoreWeight ?? 0 }}/100
                  </p>
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  <span>{{ num(row.metrics.price) }}</span><p
                    class="text-xs"
                    :class="returnClass(row.metrics.intradayReturn)"
                  >
                    {{ pct(row.metrics.intradayReturn) }}
                  </p>
                  <p class="text-[10px] text-muted-foreground">
                    {{ stamp(row.metrics.quoteTime).split(' ').at(-1) }}
                  </p>
                </TableCell>
                <TableCell
                  class="text-right tabular-nums"
                  :class="returnClass(row.metrics.relativeToMarket)"
                >
                  {{ row.metrics.marketBenchmarkSelf ? '基准自身' : pct(row.metrics.relativeToMarket) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ pct(row.metrics.sessionMeanDistancePct) }}
                </TableCell>
                <TableCell :class="row.chaseRisk === 'HIGH' ? 'font-medium text-amber-700 dark:text-amber-300' : 'text-muted-foreground'">
                  {{ intradayLabel(row.chaseRisk) }}
                </TableCell>
                <TableCell class="text-xs text-muted-foreground">
                  {{ intradayLabel(row.trend.impact ?? 'unavailable') }}
                </TableCell>
                <TableCell class="text-right text-muted-foreground tabular-nums">
                  {{ num(row.metrics.volumeRatio) }}<span v-if="typeof row.metrics.volumeRatio === 'number'">倍</span>
                </TableCell>
                <TableCell
                  v-for="[label, value] in [['3d', row.return3D], ['5d', row.return5D], ['10d', row.return10D]]"
                  :key="String(label)"
                  :data-testid="`intraday-return-${label}`"
                  class="text-right tabular-nums"
                  :class="returnClass(value)"
                >
                  {{ forwardReturn(value) }}
                </TableCell>
              </TableRow>
              <TableRow v-if="!visibleRows.length">
                <TableCell
                  :colspan="12"
                  class="py-16 text-center text-muted-foreground"
                >
                  <Search class="mx-auto mb-3 size-6 opacity-40" /><p>{{ result.status === 'not_frozen' ? '该交易日尚无冻结池。开盘后不会根据涨幅补建候选。' : '没有符合筛选条件的候选' }}</p>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
          <p class="text-xs text-muted-foreground">
            点击证券查看行情，点击行查看证据与评估轨迹
          </p><AppPagination
            :current-page="page"
            :total-pages="pageCount"
            @page-change="page = $event"
          />
        </div>
      </template>
    </section>
    <div
      v-if="result"
      class="grid gap-4 text-xs leading-relaxed text-muted-foreground lg:grid-cols-2"
    >
      <div class="space-y-1">
        <p class="font-medium text-foreground">
          如何阅读
        </p><p>“曾经确认”记录历史事件，“当前观察”表示最新评估；两者独立。高追高风险不撤销确认。</p><p>行情以各证券数据时间为准，Yahoo 可能延迟。缺失数据不按零值处理。</p><p>{{ result.rulesNote }}</p>
      </div>
      <div class="space-y-1">
        <p class="font-medium text-foreground">
          后续表现
        </p><p>3 / 5 / 10 日收益从首次确认价格起算，确认日不计入；未到期或复权基准不足时留空。</p><p>冻结于 {{ stamp(result.frozenAt) }}。量比为近似值，仅作低权重辅助。</p><p
          v-for="warning in result.warnings"
          :key="warning"
          class="text-amber-700 dark:text-amber-300"
        >
          {{ warning }}
        </p>
      </div>
    </div>
    <StockDetailDialog
      v-model:open="dialogOpen"
      :stock="selected ? { code: selected.code, name: selected.name, marketType: market } : null"
      kind="research"
      :initial-tab="detailInitialTab"
      :context="{ tradeDate: result?.tradeDate }"
    />
  </div>
</template>
