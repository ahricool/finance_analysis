<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { intradayConfirmationApi as api, type Snapshot, type Confirmation, type Market, type State, type Source } from '@/api/intradayConfirmation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const market = ref<Market>('CN');
const state = ref<State | ''>(''); const source = ref<Source | ''>('');
const result = shallowRef<Snapshot | null>(null); const selected = shallowRef<Confirmation | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false); const submitting = ref(false); const dialogOpen = ref(false); const taskId = ref('');
const sourceLabels = { confluence: '强共振', trend: 'Trend', quant: 'Quant' };
let generation = 0;
async function load() {
  const token = ++generation;
  loading.value = true; error.value = null; result.value = null; selected.value = null; dialogOpen.value = false;
  try {
    const data = await api.read(market.value, state.value || undefined, source.value || undefined);
    if (token === generation) result.value = data;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
async function run() {
  submitting.value = true; error.value = null; taskId.value = '';
  try { taskId.value = (await api.run(market.value)).taskId; }
  catch (cause) { error.value = getParsedApiError(cause); }
  finally { submitting.value = false; }
}
function pct(value: unknown) { return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : 'unavailable'; }
function num(value: unknown) { return typeof value === 'number' ? value.toFixed(2) : 'unavailable'; }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : 'unavailable'; }
function show(row: Confirmation) { selected.value = row; dialogOpen.value = true; }
onMounted(load);
onBeforeUnmount(() => { ++generation; });
</script>

<template>
  <div
    class="space-y-5"
    data-testid="intraday-confirmation-page"
  >
    <PageHeader
      title="盘中确认"
      description="昨日选谁，今日确认。只观察开盘前冻结候选，不自动交易。"
    >
      <template #actions>
        <Button
          v-if="currentUser?.role === 'admin'"
          variant="outline"
          :disabled="submitting"
          @click="run"
        >
          运行确认任务
        </Button>
        <Button
          :disabled="loading"
          @click="load"
        >
          刷新快照
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="taskId"
      class="text-sm"
    >
      任务已提交：{{ taskId }}，请在任务中心查看。运行后刷新快照。
    </p>
    <div class="flex items-center gap-4">
      <label>市场 <select
        v-model="market"
        aria-label="市场"
        class="rounded border bg-background p-2"
        @change="load"
      ><option>CN</option><option>US</option></select></label>
      <label>状态 <select
        v-model="state"
        aria-label="状态"
        class="rounded border bg-background p-2"
        @change="load"
      ><option value="">全部</option><option>CONFIRMED</option><option>WAIT</option><option>FAILED</option></select></label>
      <label>候选来源 <select
        v-model="source"
        aria-label="候选来源"
        class="rounded border bg-background p-2"
        @change="load"
      ><option value="">全部</option><option value="confluence">强共振</option><option value="trend">Trend</option><option value="quant">Quant</option></select></label>
    </div>
    <p
      v-if="loading"
      class="text-muted-foreground"
    >
      读取已计算快照…
    </p>
    <template v-if="result">
      <div class="grid grid-cols-4 gap-4">
        <div
          v-for="[label, count] in [['候选总数', result.summary.total], ['CONFIRMED', result.summary.confirmed], ['WAIT', result.summary.wait], ['FAILED', result.summary.failed]]"
          :key="label"
          class="rounded-lg border p-4"
        >
          <p class="text-sm text-muted-foreground">
            {{ label }}
          </p><p class="text-2xl font-semibold">
            {{ count }}
          </p>
        </div>
      </div>
      <div class="space-y-1 text-sm text-muted-foreground">
        <p>候选交易日 {{ result.candidateTradeDate ?? 'unavailable' }} · 当前交易日 {{ result.tradeDate }} · 冻结于 {{ stamp(result.frozenAt) }}</p>
        <p>确认生成时间 {{ stamp(result.generatedAt) }} · 行情以各股票数据时间为准，Yahoo 可能延迟。</p>
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
              <TableHead>股票 / 行情时间</TableHead><TableHead>昨夜候选原因</TableHead><TableHead>状态 / 分数</TableHead><TableHead>追高风险</TableHead><TableHead>Gap</TableHead><TableHead>5m / 15m / 30m</TableHead><TableHead>距 VWAP</TableHead><TableHead>Volume ≈</TableHead><TableHead>相对大盘</TableHead><TableHead>Temporary Trend</TableHead><TableHead>Reasons</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in result.items"
              :key="row.code"
            >
              <TableCell>
                <Button
                  variant="link"
                  class="p-0"
                  @click="show(row)"
                >
                  {{ row.name }} {{ row.code }}
                </Button><p class="text-xs text-muted-foreground">
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
                </Badge><p>{{ row.confirmationScore.toFixed(1) }}</p>
              </TableCell>
              <TableCell :class="row.chaseRisk === 'HIGH' ? 'font-semibold text-destructive' : ''">
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
            </TableRow>
            <TableRow v-if="!result.items.length">
              <TableCell
                :colspan="11"
                class="py-10 text-center text-muted-foreground"
              >
                {{ result.status === 'not_frozen' ? '尚无当天冻结池。开盘后不会根据涨幅补建候选。' : '没有符合筛选条件的候选' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </template>
    <Dialog v-model:open="dialogOpen">
      <DialogContent class="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader><DialogTitle>{{ selected?.name }} {{ selected?.code }}</DialogTitle><DialogDescription>昨日逻辑 → 今日价格行为 → 确认结论</DialogDescription></DialogHeader>
        <template v-if="selected">
          <section class="space-y-2">
            <h3 class="font-semibold">
              昨日逻辑 · {{ selected.candidateTradeDate }}
            </h3><p>{{ selected.candidateReason.join('；') }}</p><p class="text-sm text-muted-foreground">
              正式结果生成于 {{ stamp(selected.sourceGeneratedAt) }}
            </p>
          </section>
          <section class="space-y-2">
            <h3 class="font-semibold">
              今日 Price Action
            </h3>
            <p>行情时间 {{ stamp(selected.metrics.quoteTime) }} · 闭合线时间 {{ stamp(selected.metrics.barTime) }} · 确认生成 {{ stamp(selected.generatedAt) }}</p>
            <p>Gap {{ pct(selected.metrics.gapPct) }} · {{ selected.metrics.gapStatus }}</p>
            <p>5m {{ pct(selected.metrics.return5M) }} / 15m {{ pct(selected.metrics.return15M) }} / 30m {{ pct(selected.metrics.return30M) }}</p>
            <p>Opening Range {{ num(selected.metrics.openingRangeLow) }} – {{ num(selected.metrics.openingRangeHigh) }}</p>
            <p>provisional VWAP {{ num(selected.metrics.vwap) }} · 距离 {{ pct(selected.metrics.vwapDistancePct) }}</p>
            <p>Volume {{ num(selected.metrics.volumeRatio) }}x · {{ selected.metrics.volumeStatus }}（日均量 × 交易时间比例近似）</p>
          </section>
          <section class="space-y-2">
            <h3 class="font-semibold">
              Relative Strength（统一以开盘为基准）
            </h3><p>{{ selected.metrics.benchmarkCode }}：{{ pct(selected.metrics.relativeToMarket) }} · 数据时间 {{ stamp(selected.metrics.benchmarkQuoteTime) }}</p><p>Industry：unavailable · {{ selected.metrics.industryUnavailableReason }}</p><p>ETF：unavailable · {{ selected.metrics.etfUnavailableReason }}</p>
          </section>
          <section class="space-y-2">
            <h3 class="font-semibold">
              Trend Impact · Official → Temporary
            </h3>
            <p>{{ selected.trend.officialTrendState ?? 'unavailable' }} → {{ selected.trend.temporaryTrendState ?? 'unavailable' }}</p>
            <p>Lifecycle {{ selected.trend.officialLifecycle ?? 'unavailable' }} → {{ selected.trend.temporaryLifecycle ?? 'unavailable' }}</p>
            <p>Trend Score Δ {{ num(selected.trend.trendScoreDelta) }} · Fragility {{ num(selected.trend.officialFragility) }} → unavailable</p>
            <p class="text-sm text-muted-foreground">
              {{ selected.trend.calculationBasis }}。{{ selected.trend.fragilityUnavailableReason }}
            </p>
          </section>
          <section class="space-y-2">
            <h3 class="font-semibold">
              Decision · {{ selected.state }} · Chase Risk {{ selected.chaseRisk }}
            </h3><ul class="list-disc pl-5">
              <li
                v-for="reason in selected.reasons"
                :key="reason.code"
              >
                {{ reason.text }}
              </li>
            </ul>
            <p v-if="selected.currentPriceRecovered">
              当前价格行为已恢复，但本次候选当日 FAILED 不自动恢复。
            </p>
            <template v-if="selected.stateReasons.length">
              <p>状态变更时依据：</p><ul class="list-disc pl-5">
                <li
                  v-for="reason in selected.stateReasons"
                  :key="reason.code"
                >
                  {{ reason.text }}
                </li>
              </ul>
            </template>
          </section>
        </template>
      </DialogContent>
    </Dialog>
  </div>
</template>
