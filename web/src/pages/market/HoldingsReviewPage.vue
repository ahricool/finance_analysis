<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { ArrowDownRight, ArrowUpRight, CalendarClock, Check, ChevronLeft, ChevronRight, CircleAlert, Clock3, FileDown, Layers3, LoaderCircle, RefreshCw, ShieldCheck, Sparkles } from 'lucide-vue-next';
import { holdingsReviewApi as api, type FrozenHolding, type HoldingAdvice, type ReviewAction, type ReviewResponse } from '@/api/holdingsReview';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useMarket } from '@/composables/useMarket';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import StockLink from '@/components/stocks/StockLink.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';

const { market } = useMarket();
const response = shallowRef<ReviewResponse | null>(null);
const dates = ref<Array<{ tradeDate: string; status: string }>>([]);
const chosenDate = ref('');
const loading = ref(false), running = ref(false), queued = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const runError = shallowRef<ParsedApiError | null>(null);
const review = computed(() => response.value?.review ?? null);
const decision = computed(() => review.value?.decision ?? null);
const isHistorical = computed(() => !!review.value && review.value.tradeDate !== response.value?.today);
const displayDate = computed(() => chosenDate.value || review.value?.tradeDate || response.value?.today || '');
const confidence = { HIGH: '高', MEDIUM: '中', LOW: '低' };
const actions: Record<ReviewAction, string> = { HOLD: '维持', BUY: '加仓', REDUCE: '减仓', SELL: '退出', WATCH: '观察' };
const states = { RISK_ON: '偏强运行', NEUTRAL: '均衡观察', RISK_OFF: '风险收缩', UNCERTAIN: '等待确认' };
const priority: Record<ReviewAction, number> = { SELL: 5, REDUCE: 4, BUY: 3, WATCH: 2, HOLD: 1 };
const badgeClasses: Record<ReviewAction, string> = {
  BUY: 'border-brand/25 bg-brand/10 text-brand', SELL: 'border-destructive/25 bg-destructive/10 text-destructive',
  REDUCE: 'border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  HOLD: 'border-border bg-muted text-foreground', WATCH: 'border-border bg-transparent text-muted-foreground',
};
type SortKey = 'name' | 'action' | 'quantity' | 'currentPrice' | 'unrealizedPnlPct' | 'weightPct';
const sortKey = ref<SortKey>('action');
const direction = ref<'asc' | 'desc'>('desc');
const columns: Array<{ key: SortKey; label: string }> = [
  { key: 'name', label: '持仓标的' }, { key: 'action', label: '复盘建议' },
  { key: 'quantity', label: '持仓数量' }, { key: 'currentPrice', label: '快照现价' },
  { key: 'unrealizedPnlPct', label: '持仓盈亏' }, { key: 'weightPct', label: '持仓权重' },
];
type Row = FrozenHolding & { advice: HoldingAdvice };
const rows = computed<Row[]>(() => {
  const positions = new Map((review.value?.holdings || []).map(p => [p.positionId, p]));
  const result = (decision.value?.positions || []).flatMap(advice => {
    const p = positions.get(advice.positionId); return p ? [{ ...p, advice }] : [];
  });
  function value(row: Row) { return sortKey.value === 'action' ? priority[row.advice.action] : row[sortKey.value]; }
  return result.sort((a, b) => {
    const x = value(a), y = value(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    const order = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-CN');
    return order * (direction.value === 'asc' ? 1 : -1) || a.positionId.localeCompare(b.positionId);
  });
});
const actionCount = computed(() => (decision.value?.positions || []).filter(p => ['BUY', 'REDUCE', 'SELL'].includes(p.action)).length);
const sourceRows = computed(() => [
  { label: 'ETF 轮动预演', value: review.value?.research.etfRotation },
  { label: '持仓趋势预演', value: review.value?.research.holdingTrends },
  { label: '行业强度预演', value: review.value?.research.industryStrength },
]);
const sourceLinks = computed(() => review.value?.searchEvidence.status === 'confirmed'
  ? (review.value.searchEvidence.citations || []).filter(s => /^https?:\/\//i.test(s.url)).slice(0, 8) : []);
let generation = 0, runGeneration = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
function clearPoll() { if (timer) clearTimeout(timer); timer = undefined; }
async function load(withDates = true) {
  const token = ++generation;
  const selectedMarket = market.value;
  clearPoll(); loading.value = true; error.value = null;
  try {
    const [result, available] = await Promise.all([api.detail(selectedMarket, chosenDate.value || undefined),
      withDates ? api.dates(selectedMarket) : Promise.resolve(dates.value)]);
    if (token !== generation) return;
    response.value = result;
    dates.value = result.review ? [
      { tradeDate: result.review.tradeDate, status: result.review.status },
      ...available.filter(item => item.tradeDate !== result.review?.tradeDate),
    ].sort((a, b) => b.tradeDate.localeCompare(a.tradeDate)) : available;
    if (result.review?.status === 'processing' || queued.value) {
      if (result.review?.tradeDate === result.today && ['completed', 'failed'].includes(result.review.status)) queued.value = false;
      else timer = setTimeout(() => { void load(false); }, 5000);
    }
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function changeDate(value: string) { ++runGeneration; running.value = false; runError.value = null; chosenDate.value = value; response.value = null; queued.value = false; void load(false); }
function moveDate(delta: number) {
  const index = dates.value.findIndex(d => d.tradeDate === displayDate.value);
  const next = dates.value[index + delta]; if (next) changeDate(next.tradeDate);
}
async function run() {
  const token = ++runGeneration;
  running.value = true; runError.value = null;
  try {
    await api.run(market.value);
    if (token !== runGeneration) return;
    chosenDate.value = ''; queued.value = true; await load();
  } catch (cause) { if (token === runGeneration) runError.value = getParsedApiError(cause); }
  finally { if (token === runGeneration) running.value = false; }
}
function sort(key: SortKey) {
  if (sortKey.value === key) direction.value = direction.value === 'asc' ? 'desc' : 'asc';
  else { sortKey.value = key; direction.value = key === 'name' ? 'asc' : 'desc'; }
}
function fmt(value?: number | null, digits = 2) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}
function signed(value?: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value)}%`; }
function tone(value?: number | null) { return value == null || value === 0 ? '' : value > 0 ? 'text-market-up' : 'text-market-down'; }
function time(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: market.value === 'CN' ? 'Asia/Shanghai' : 'America/New_York',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}
function download() {
  if (!review.value?.markdown) return;
  const url = URL.createObjectURL(new Blob([review.value.markdown], { type: 'text/markdown;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = `持仓复盘-${market.value}-${review.value.tradeDate}.md`;
  a.click(); URL.revokeObjectURL(url);
}
watch(market, () => {
  ++runGeneration; running.value = false; queued.value = false; runError.value = null;
  chosenDate.value = ''; response.value = null; dates.value = []; sortKey.value = 'action'; direction.value = 'desc';
  void load();
}, { immediate: true });
onBeforeUnmount(() => { ++generation; ++runGeneration; clearPoll(); });
</script>

<template>
  <div
    class="space-y-6"
    data-testid="holdings-review-page"
  >
    <PageHeader
      variant="section"
      title="持仓复盘"
      en="Portfolio Review"
      description="收盘前 50 分钟，结合市场、研究预演与真实持仓，记录每一天的判断依据。"
    >
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label="上一份复盘"
            :disabled="dates.findIndex(d => d.tradeDate === displayDate) < 0 || dates.findIndex(d => d.tradeDate === displayDate) >= dates.length - 1"
            @click="moveDate(1)"
          >
            <ChevronLeft class="size-4" />
          </Button>
          <AppDatePicker
            id="holdings-review-date"
            :model-value="displayDate"
            :available-dates="dates.map(d => d.tradeDate)"
            :clearable="false"
            class="w-44"
            @update:model-value="changeDate"
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="下一份复盘"
            :disabled="dates.findIndex(d => d.tradeDate === displayDate) <= 0"
            @click="moveDate(-1)"
          >
            <ChevronRight class="size-4" />
          </Button>
          <Button
            variant="outline"
            :disabled="loading"
            @click="chosenDate = ''; load()"
          >
            最新复盘
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新复盘"
            :disabled="loading"
            @click="load()"
          >
            <RefreshCw
              class="size-4"
              :class="{ 'animate-spin': loading }"
            />
          </Button>
        </div>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load()"
    />
    <AppApiErrorAlert
      v-if="runError"
      :error="runError"
    />
    <div
      v-if="loading && !response"
      class="space-y-4"
      role="status"
      aria-label="正在加载持仓复盘"
    >
      <div class="h-48 animate-pulse rounded-2xl bg-muted" /><div class="grid gap-4 md:grid-cols-3">
        <div
          v-for="n in 3"
          :key="n"
          class="h-24 animate-pulse rounded-xl bg-muted"
        />
      </div>
    </div>
    <template v-else-if="response">
      <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
        <div class="flex flex-wrap items-center gap-3 text-muted-foreground">
          <CalendarClock class="size-4 text-brand" /><span class="font-medium text-foreground">{{ market === 'CN' ? 'A 股' : '美股' }} · {{ review?.tradeDate || displayDate }}</span><Badge
            v-if="isHistorical"
            variant="outline"
          >
            历史快照
          </Badge><span>{{ review?.asOf ? `采集于 ${time(review.asOf)}` : `计划于 ${time(response.scheduledAt)}` }} {{ market === 'CN' ? '北京时间' : '纽约时间' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <Button
            v-if="response.canRun"
            size="sm"
            :disabled="running || queued"
            @click="run"
          >
            <LoaderCircle
              v-if="running || queued"
              class="mr-1 size-3.5 animate-spin"
            />运行本日复盘
          </Button><Button
            v-if="review?.markdown"
            variant="ghost"
            size="sm"
            @click="download"
          >
            <FileDown class="mr-1 size-3.5" />下载 Markdown
          </Button>
        </div>
      </div>
      <div
        v-if="!review || review.status !== 'completed'"
        class="flex min-h-80 flex-col items-center justify-center rounded-2xl border border-dashed bg-card px-6 text-center"
        data-testid="review-empty"
      >
        <div class="mb-5 rounded-2xl bg-brand/10 p-4 text-brand">
          <LoaderCircle
            v-if="queued || review?.status === 'processing'"
            class="size-7 animate-spin"
          /><CircleAlert
            v-else-if="review?.status === 'failed'"
            class="size-7"
          /><Clock3
            v-else
            class="size-7"
          />
        </div>
        <h2 class="text-lg font-semibold">
          {{ queued || review?.status === 'processing' ? '正在生成持仓复盘' : review?.status === 'failed' ? '本次复盘未完成' : '所选日期暂无复盘' }}
        </h2>
        <p class="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
          {{ review?.error || (queued || review?.status === 'processing' ? '正在核对市场与持仓证据，联网研究可能需要几分钟。页面会自动更新。' : '复盘在交易日收盘前 50 分钟生成。可选择有记录的历史日期查看，历史报告不会用今天的数据重算。') }}
        </p>
      </div>
      <template v-else-if="decision">
        <p
          v-if="queued && review.tradeDate !== response.today"
          class="rounded-xl border border-brand/20 bg-brand/5 px-4 py-3 text-sm"
          role="status"
        >
          今日复盘已排队，暂时展示上一交易日的已保存结果；完成后会自动更新。
        </p>
        <div
          v-if="decision.degraded"
          class="flex gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm"
        >
          <CircleAlert class="mt-0.5 size-4 shrink-0 text-amber-600" /><div>
            <strong>本次为降级复盘</strong><p class="mt-1 text-muted-foreground">
              未取得有效的结构化模型结论，仅保留观察建议与采集证据。
            </p>
          </div>
        </div>
        <div class="grid gap-5 xl:grid-cols-3">
          <section
            class="relative overflow-hidden rounded-2xl border bg-card p-6 xl:col-span-2"
            data-testid="review-market-conclusion"
          >
            <div class="absolute right-0 top-0 size-44 rounded-full bg-brand/5 blur-3xl" />
            <div class="relative">
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 text-sm font-medium">
                  <Sparkles class="size-4 text-brand" />市场结论<span class="text-xs font-normal text-muted-foreground">Market Outlook</span>
                </div><Badge variant="outline">
                  置信度 · {{ confidence[decision.confidence] }}
                </Badge>
              </div><h2 class="mt-5 text-2xl font-semibold tracking-tight">
                {{ states[decision.marketState] }}
              </h2><p class="mt-3 whitespace-pre-line text-sm leading-7 text-muted-foreground">
                {{ decision.conclusion }}
              </p>
              <div class="mt-6 grid gap-3 border-t pt-4 sm:grid-cols-3">
                <div
                  v-for="index in review.indices"
                  :key="index.symbol"
                >
                  <div class="text-xs text-muted-foreground">
                    {{ index.name }}
                  </div><div class="mt-1 flex items-baseline gap-2">
                    <span class="font-semibold tabular-nums">{{ fmt(index.currentPrice) }}</span><span
                      class="text-xs tabular-nums"
                      :class="tone(index.changePct)"
                    >{{ signed(index.changePct) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
          <section class="rounded-2xl border bg-card p-6">
            <div class="flex items-center gap-2 text-sm font-medium">
              <Layers3 class="size-4 text-brand" />组合快照<span class="text-xs font-normal text-muted-foreground">Portfolio</span>
            </div><div class="mt-5 text-3xl font-semibold tabular-nums tracking-tight">
              {{ fmt(review.portfolio.nav) }}<span class="ml-2 text-xs font-normal text-muted-foreground">{{ review.portfolio.currency }}</span>
            </div><p class="mt-1 text-xs text-muted-foreground">
              {{ review.portfolio.valuationComplete ? '采集时点总资产' : '报价不完整，无法汇总总资产' }}
            </p><div class="mt-5 grid grid-cols-3 gap-2 border-t pt-4">
              <div>
                <div class="text-xs text-muted-foreground">
                  持仓标的
                </div><div class="mt-1 text-lg font-semibold">
                  {{ review.holdings.length }}
                </div>
              </div><div>
                <div class="text-xs text-muted-foreground">
                  建议调整
                </div><div class="mt-1 text-lg font-semibold text-brand">
                  {{ actionCount }}
                </div>
              </div><div>
                <div class="text-xs text-muted-foreground">
                  风险提示
                </div><div class="mt-1 text-lg font-semibold">
                  {{ decision.risks.length }}
                </div>
              </div>
            </div>
          </section>
        </div>
        <div class="grid gap-5 lg:grid-cols-2">
          <section class="rounded-2xl border bg-card p-6">
            <h2 class="text-sm font-semibold">
              板块强弱 <span class="ml-1 text-xs font-normal text-muted-foreground">Sector Pulse</span>
            </h2><p
              v-if="!decision.sectors.length"
              class="mt-4 text-sm text-muted-foreground"
            >
              未形成可靠板块判断。
            </p><div
              v-for="(sector, i) in decision.sectors"
              :key="sector.name"
              class="flex gap-3 border-b py-4 last:border-0 last:pb-0"
            >
              <span class="mt-0.5 text-xs tabular-nums text-muted-foreground">{{ String(i + 1).padStart(2, '0') }}</span><div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium">{{ sector.name }}</span><ArrowUpRight
                    v-if="sector.strength === 'STRONG'"
                    class="size-4 text-market-up"
                  /><ArrowDownRight
                    v-else-if="sector.strength === 'WEAK'"
                    class="size-4 text-market-down"
                  /><span class="text-xs text-muted-foreground">{{ sector.strength === 'STRONG' ? '强势' : sector.strength === 'WEAK' ? '偏弱' : '中性' }}</span>
                </div><p class="mt-1 text-sm leading-6 text-muted-foreground">
                  {{ sector.rationale }}
                </p>
              </div>
            </div>
          </section>
          <section class="rounded-2xl border bg-card p-6">
            <h2 class="text-sm font-semibold">
              风险与观察 <span class="ml-1 text-xs font-normal text-muted-foreground">Risk Monitor</span>
            </h2><div
              v-for="risk in decision.risks"
              :key="risk.title"
              class="mt-4 rounded-lg border-l-2 bg-muted/40 px-4 py-3"
              :class="risk.severity === 'HIGH' ? 'border-destructive' : risk.severity === 'MEDIUM' ? 'border-amber-500' : 'border-border'"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="text-sm font-medium">{{ risk.title }}</span><span class="text-xs text-muted-foreground">{{ risk.severity === 'HIGH' ? '高' : risk.severity === 'MEDIUM' ? '中' : '低' }}</span>
              </div><p class="mt-1 text-sm leading-6 text-muted-foreground">
                {{ risk.detail }}
              </p>
            </div><ul
              v-if="decision.watchpoints.length"
              class="mt-4 space-y-2 border-t pt-4 text-sm leading-6 text-muted-foreground"
            >
              <li
                v-for="point in decision.watchpoints"
                :key="point"
                class="flex gap-2"
              >
                <span class="text-brand">·</span>{{ point }}
              </li>
            </ul>
          </section>
        </div>
        <section
          class="overflow-hidden rounded-2xl border bg-card"
          data-testid="review-holdings"
        >
          <div class="flex flex-wrap items-center justify-between gap-2 border-b px-6 py-5">
            <h2 class="text-sm font-semibold">
              持仓操作建议 <span class="ml-1 text-xs font-normal text-muted-foreground">Position Decisions</span>
            </h2><span class="text-xs text-muted-foreground">BUY 为已有持仓加仓 · 比例相对于该笔持仓</span>
          </div>
          <p
            v-if="!rows.length"
            class="p-8 text-center text-sm text-muted-foreground"
          >
            该市场暂无已登记持仓，不生成新建仓建议。
          </p>
          <div
            v-else
            class="overflow-x-auto"
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableTableHeader
                    v-for="column in columns"
                    :key="column.key"
                    :label="column.label"
                    :active="sortKey === column.key"
                    :direction="direction"
                    :align="['name', 'action'].includes(column.key) ? 'left' : 'right'"
                    @sort="sort(column.key)"
                  />
                </TableRow>
              </TableHeader><TableBody>
                <template
                  v-for="row in rows"
                  :key="row.positionId"
                >
                  <TableRow data-testid="review-position-row">
                    <TableCell class="min-w-40 pl-6">
                      <StockLink
                        :code="row.symbol"
                        :name="row.name"
                        :market="market"
                      /><div class="mt-1 text-xs text-muted-foreground">
                        {{ row.accountName || `账户 ${row.accountId}` }}
                      </div>
                    </TableCell><TableCell>
                      <Badge
                        variant="outline"
                        :class="badgeClasses[row.advice.action]"
                      >
                        {{ actions[row.advice.action] }}
                      </Badge><div class="mt-1 text-xs text-muted-foreground">
                        {{ row.advice.changePct ? `${row.advice.changePct}% 当前持仓` : row.advice.action === 'WATCH' ? '等待条件确认' : '保持现有规模' }}
                      </div>
                    </TableCell><TableCell class="text-right tabular-nums">
                      {{ fmt(row.quantity, 4) }}
                    </TableCell><TableCell class="text-right tabular-nums">
                      {{ fmt(row.currentPrice) }}<div class="mt-1 text-xs text-muted-foreground">
                        成本 {{ fmt(row.averageCost) }}
                      </div>
                    </TableCell><TableCell
                      class="text-right tabular-nums"
                      :class="tone(row.unrealizedPnlPct)"
                    >
                      {{ signed(row.unrealizedPnlPct) }}
                    </TableCell><TableCell class="pr-6 text-right tabular-nums">
                      {{ row.weightPct == null ? '—' : `${fmt(row.weightPct)}%` }}
                    </TableCell>
                  </TableRow><TableRow class="hover:bg-transparent">
                    <TableCell
                      :colspan="6"
                      class="px-6 pb-5 pt-0"
                    >
                      <div class="rounded-lg bg-muted/40 p-4">
                        <p class="text-sm leading-6">
                          {{ row.advice.rationale }}
                        </p><div
                          v-if="row.advice.condition || row.advice.invalidation"
                          class="mt-3 grid gap-3 border-t pt-3 text-xs leading-5 md:grid-cols-2"
                        >
                          <div v-if="row.advice.condition">
                            <span class="font-medium text-brand">触发条件</span><p class="mt-1 text-muted-foreground">
                              {{ row.advice.condition }}
                            </p>
                          </div><div v-if="row.advice.invalidation">
                            <span class="font-medium">判断失效</span><p class="mt-1 text-muted-foreground">
                              {{ row.advice.invalidation }}
                            </p>
                          </div>
                        </div><p
                          v-if="market === 'CN' && row.todayBuyQuantity > 0"
                          class="mt-2 text-xs text-muted-foreground"
                        >
                          当日买入 {{ fmt(row.todayBuyQuantity, 4) }}，卖出建议需扣除 T+1 限售部分。
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                </template>
              </TableBody>
            </Table>
          </div>
        </section>
        <section class="rounded-2xl border bg-card p-6">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck class="size-4 text-brand" />证据与数据时点
            </h2><span class="text-xs text-muted-foreground">历史结果来自当时快照，查看时不重新计算</span>
          </div><div class="mt-4 grid gap-3 md:grid-cols-3">
            <div
              v-for="source in sourceRows"
              :key="source.label"
              class="flex items-start gap-2 rounded-lg bg-muted/40 p-3"
            >
              <Check
                v-if="source.value?.status === 'available'"
                class="mt-0.5 size-4 shrink-0 text-brand"
              /><CircleAlert
                v-else
                class="mt-0.5 size-4 shrink-0 text-muted-foreground"
              /><div class="min-w-0">
                <div class="text-xs font-medium">
                  {{ source.label }}
                </div><div class="mt-1 text-xs text-muted-foreground">
                  {{ source.value?.status === 'available' ? `${time(source.value.observedAt)} · ${source.value.items.length} 项摘要` : source.value?.status === 'unsupported' ? '该市场暂不覆盖' : '当前有效数据缺失' }}
                </div>
              </div>
            </div>
          </div><div class="mt-4 text-xs leading-6 text-muted-foreground">
            <p>联网核验：{{ review.searchEvidence.status === 'confirmed' ? '已取得工具执行证据' : review.searchEvidence.status === 'unavailable' ? '当前后端不支持联网，结论仅依据输入数据' : '未取得可验证的搜索证据' }}。</p><p
              v-for="note in review.dataQuality"
              :key="note"
            >
              {{ note }}
            </p>
          </div><div
            v-if="sourceLinks.length"
            class="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t pt-4"
          >
            <a
              v-for="source in sourceLinks"
              :key="source.url"
              :href="source.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-xs text-brand underline underline-offset-4"
            >{{ source.title || source.url }}</a>
          </div>
        </section>
        <p class="px-1 text-xs leading-6 text-muted-foreground">
          复盘仅提供持仓研究建议，不自动下单。{{ market === 'CN' ? 'A股需核对 T+1 与实际可卖数量。' : '' }}现金为手动登记余额，请以券商实际可用资金为准。
        </p>
      </template>
    </template>
  </div>
</template>
