<script setup lang="ts">
import { formatFixed, formatPercent } from '@/utils/number';
import StockLink from '@/components/stocks/StockLink.vue';
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
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
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const market = ref<Market>('CN');
const tradeDate = ref(''); const dates = ref<string[]>([]);
const datesLoading = ref(false); const datesError = shallowRef<ParsedApiError | null>(null);
const state = ref<State | ''>(''); const source = ref<Source | ''>('');
const result = shallowRef<Snapshot | null>(null); const selected = shallowRef<Confirmation | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false); const submitting = ref(false); const dialogOpen = ref(false); const taskId = ref('');
const sourceLabels = { confluence: '强共振', trend: 'Trend', quant: 'Quant' };
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
function pct(value: unknown) { return formatPercent(value, { digits: 2, fallback: 'unavailable' }); }
function num(value: unknown) { return formatFixed(value, { fallback: 'unavailable' }); }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : 'unavailable'; }
function show(row: Confirmation) { selected.value = row; dialogOpen.value = true; }
onMounted(refresh);
onBeforeUnmount(() => { ++generation; ++datesGeneration; ++runGeneration; controller?.abort(); datesController?.abort(); });
function forwardReturn(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : ''; }
function returnClass(value: unknown) { return typeof value === 'number' && value > 0 ? 'text-market-up' : typeof value === 'number' && value < 0 ? 'text-market-down' : ''; }
const detailInitialTab = ref<'overview' | 'intraday'>('intraday');
</script>

<template>
  <div
    class="space-y-5"
    data-testid="intraday-confirmation-page"
  >
    <PageHeader
      variant="section"
      title="盘中确认"
      en="Intraday Confirmation"
      description="昨日选谁，今日确认。查看开盘前冻结候选、历史确认与确认后收益，不自动交易。"
    >
      <template #actions>
        <div class="flex min-w-0 flex-wrap items-end gap-2">
          <ResearchMarketToggle
            :model-value="market"
            data-testid="intraday-market-switcher"
            @update:model-value="setMarket"
          />
          <label>交易日 <select
            v-model="tradeDate"
            aria-label="交易日"
            data-testid="intraday-date-selector"
            class="h-10 rounded-md border border-input bg-background px-3 text-sm"
            @change="load"
          ><option value="">当日</option><option
            v-for="date in dates"
            :key="date"
            :value="date"
          >{{ date }}</option></select></label>
          <span
            v-if="datesLoading"
            class="text-xs text-muted-foreground"
          >读取历史日期…</span>
          <label>状态 <select
            v-model="state"
            aria-label="状态"
            class="h-10 rounded-md border border-input bg-background px-3 text-sm"
            @change="load"
          ><option value="">全部</option><option>CONFIRMED</option><option>WAIT</option><option>FAILED</option></select></label>
          <label>候选来源 <select
            v-model="source"
            aria-label="候选来源"
            class="h-10 rounded-md border border-input bg-background px-3 text-sm"
            @change="load"
          ><option value="">全部</option><option value="confluence">强共振</option><option value="trend">Trend</option><option value="quant">Quant</option></select></label>
        </div>
        <Button
          variant="outline"
          :disabled="loading"
          @click="refresh"
        >
          刷新快照
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
      <AppApiErrorAlert :error="datesError" />
      <Button
        variant="outline"
        @click="loadDates"
      >
        重试历史日期
      </Button>
    </div>
    <p
      v-if="tradeDate"
      class="text-sm text-muted-foreground"
    >
      历史快照 {{ tradeDate }}，只读查看；确认任务仅计算当日。
    </p>
    <p
      v-if="taskId"
      class="text-sm"
    >
      任务已提交：{{ taskId }}，请在任务中心查看。运行后刷新快照。
    </p>

    <p
      v-if="loading"
      class="text-muted-foreground"
    >
      读取已计算快照…
    </p>
    <template v-if="result">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div
          v-for="[label, count] in [['候选总数', result.summary.total], ['CONFIRMED', result.summary.confirmed], ['WAIT', result.summary.wait], ['FAILED', result.summary.failed]]"
          :key="label"
          class="rounded-lg border p-4"
        >
          <p class="text-sm text-muted-foreground">
            <IndicatorHelpLabel
              scope="intraday"
              :label="String(label)"
            />
          </p><p class="text-2xl font-semibold">
            {{ count }}
          </p>
        </div>
      </div>
      <div class="space-y-1 text-sm text-muted-foreground">
        <p>候选交易日 {{ result.candidateTradeDate ?? 'unavailable' }} · 确认交易日 {{ result.tradeDate }} · 冻结于 {{ stamp(result.frozenAt) }}</p>
        <p>确认生成时间 {{ stamp(result.generatedAt) }} · 行情以各股票数据时间为准，Yahoo 可能延迟。</p>
        <p>+3/5/10D 从首次确认价格起算，确认日不计入，按后续交易日收盘计算；未到期或价格、复权基准不足时留空。</p>
        <p>{{ result.rulesNote }}</p><p>unavailable 表示数据不足，不代表负向；量能为日均量按已过交易时间的近似值。</p>
        <p
          v-for="warning in result.warnings"
          :key="warning"
        >
          {{ warning }}
        </p>
      </div>
      <div class="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="股票 / 行情时间"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="昨夜候选原因"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="状态 / 分数"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="追高风险"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="Gap"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="5m / 15m / 30m"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="距 VWAP"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="成交量≈"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="相对大盘"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="temporaryTrend"
                  compact
                />
              </TableHead><TableHead>
                <IndicatorHelpLabel
                  scope="intraday"
                  label="reasons"
                  compact
                />
              </TableHead>
              <TableHead
                v-for="label in ['+3D', '+5D', '+10D']"
                :key="label"
              >
                <IndicatorHelpLabel
                  scope="intraday"
                  :label="label"
                  compact
                />
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in result.items"
              :key="row.code"
              class="cursor-pointer"
              tabindex="0"
              @click="detailInitialTab = 'intraday'; show(row)"
              @keydown.enter.self="detailInitialTab = 'intraday'; show(row)"
              @keydown.space.self.prevent="detailInitialTab = 'intraday'; show(row)"
            >
              <TableCell>
                <StockLink
                  :code="row.code"
                  :name="row.name"
                  :market="market"
                  @select="detailInitialTab = 'overview'; show(row)"
                /><p class="text-xs text-muted-foreground">
                  {{ stamp(row.metrics.quoteTime) }}
                </p>
              </TableCell>
              <TableCell class="max-w-48 whitespace-normal">
                <Badge variant="outline">
                  {{ sourceLabels[row.candidateSource] }}
                </Badge><p>{{ row.candidateReason.join('；') }}</p>
              </TableCell>
              <TableCell>
                <Badge :variant="row.state === 'FAILED' ? 'destructive' : 'secondary'">
                  {{ row.state }}
                </Badge><p>{{ row.confirmationScore == null ? 'unavailable' : row.confirmationScore.toFixed(1) }}</p>
                <p class="text-xs text-muted-foreground">
                  有效权重 {{ row.availableScoreWeight ?? 0 }}/100
                </p>
              </TableCell>
              <TableCell :class="row.chaseRisk === 'HIGH' ? 'font-semibold text-destructive' : row.chaseRisk === 'UNKNOWN' ? 'text-muted-foreground' : ''">
                {{ row.chaseRisk }}
              </TableCell>
              <TableCell>{{ pct(row.metrics.gapPct) }}</TableCell>
              <TableCell><p>{{ pct(row.metrics.return5M) }}</p><p>{{ pct(row.metrics.return15M) }}</p><p>{{ pct(row.metrics.return30M) }}</p></TableCell>
              <TableCell>{{ pct(row.metrics.vwapDistancePct) }}</TableCell>
              <TableCell>{{ num(row.metrics.volumeRatio) }}<span v-if="typeof row.metrics.volumeRatio === 'number'">x</span></TableCell>
              <TableCell>{{ pct(row.metrics.relativeToMarket) }}</TableCell>
              <TableCell>{{ row.trend.impact ?? 'unavailable' }}</TableCell>
              <TableCell class="max-w-64 whitespace-normal text-xs">
                {{ row.reasons.slice(0, 3).map(r => r.text).join('；') }}
              </TableCell>
              <TableCell
                v-for="[label, value] in [['3d', row.return3D], ['5d', row.return5D], ['10d', row.return10D]]"
                :key="String(label)"
                :data-testid="`intraday-return-${label}`"
                :class="returnClass(value)"
              >
                {{ forwardReturn(value) }}
              </TableCell>
            </TableRow>
            <TableRow v-if="!result.items.length">
              <TableCell
                :colspan="14"
                class="py-10 text-center text-muted-foreground"
              >
                {{ result.status === 'not_frozen' ? '该交易日尚无冻结池。开盘后不会根据涨幅补建候选。' : '没有符合筛选条件的候选' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </template>
    <StockDetailDialog
      v-model:open="dialogOpen"
      :stock="selected ? { code: selected.code, name: selected.name, market_type: market } : null"
      kind="research"
      :initial-tab="detailInitialTab"
      :context="{ tradeDate: result?.tradeDate }"
    />
  </div>
</template>
