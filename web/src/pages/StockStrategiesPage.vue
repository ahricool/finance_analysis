<script setup lang="ts">
import { formatPercent } from '@/utils/number';
import { computed, defineAsyncComponent, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import { ArrowLeft, ArrowUpRight, RefreshCcw } from 'lucide-vue-next';
import PageHeader from '@/components/layout/PageHeader.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import StockLink from '@/components/stocks/StockLink.vue';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { stockStrategiesApi as api, type Market, type Overview, type Detail, type Day, type Metrics } from '@/api/stockStrategies';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import { formatDateTime } from '@/utils/format';

const PerformanceChart = defineAsyncComponent(() => import('@/components/stock-strategies/PerformanceChart.vue'));
const route = useRoute(); const router = useRouter(); const { currentUser } = useAuth();
const market = computed<Market>(() => route.query.market === 'US' ? 'US' : 'CN');
const key = computed(() => typeof route.params.strategyKey === 'string' ? route.params.strategyKey : '');
const overview = shallowRef<Overview | null>(null); const detail = shallowRef<Detail | null>(null);
const error = shallowRef<ParsedApiError | null>(null); const loading = ref(false); const submitting = ref(false);
const moreLoading = ref(false); const taskId = ref(''); let generation = 0;
const latest = computed(() => detail.value?.latest);
const nextPlan = computed(() => latest.value?.payload.plan);
const positions = computed(() => Object.entries(latest.value?.payload.positions ?? {}));
const statuses = { success: '已结算', waiting: '等待数据', failed: '运行失败', not_started: '尚未启动', catching_up: '等待补算' };
const pct = (v: number | null | undefined) => formatPercent(v, { digits: 2, signed: true });
const number = (v: number | undefined | null, digits = 2) => v == null ? '—' : v.toLocaleString('zh-CN', { maximumFractionDigits: digits });
const tone = (v: number | undefined | null) => v == null || v === 0 ? '' : v > 0 ? 'text-market-up' : 'text-market-down';
const metricColumns = [
  { key: 'dailyReturn', zh: '结算日收益', en: 'Daily return' }, { key: 'totalReturn', zh: '累计收益', en: 'Total return' },
  { key: 'cagr', zh: '复合年化', en: 'CAGR' }, { key: 'maxDrawdown', zh: '最大回撤', en: 'Max drawdown' },
  { key: 'exposure', zh: '持仓比例', en: 'Exposure' },
] as const;
const counts = computed(() => ({ total: overview.value?.items.length ?? 0,
  failed: overview.value?.items.filter(r => r.status === 'failed').length ?? 0,
  waiting: overview.value?.items.filter(r => r.status === 'waiting').length ?? 0 }));
async function load() {
  const token = ++generation; loading.value = true; error.value = null;
  overview.value = null; detail.value = null; taskId.value = ''; moreLoading.value = false;
  try {
    if (key.value) {
      const response = await api.detail(key.value, market.value);
      if (token === generation) detail.value = response;
    } else {
      const response = await api.overview(market.value);
      if (token === generation) overview.value = response;
    }
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
async function loadMore() {
  if (!detail.value?.nextBefore || moreLoading.value) return;
  const token = generation; moreLoading.value = true;
  try {
    const response = await api.detail(key.value, market.value, detail.value.nextBefore);
    if (token !== generation || !detail.value) return;
    detail.value = { ...detail.value, days: [...detail.value.days, ...response.days], nextBefore: response.nextBefore };
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) moreLoading.value = false; }
}
function setMarket(value: Market) {
  if (market.value !== value) void router.push({ path: '/strategies', query: { market: value } });
}
function show(strategyKey: string) { void router.push({ name: 'strategy-detail', params: { strategyKey }, query: { market: market.value } }); }
async function run() {
  const token = generation; submitting.value = true; error.value = null;
  try {
    const result = await api.run(market.value, key.value || undefined);
    if (token === generation) taskId.value = result.taskId;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { submitting.value = false; }
}
function dayAction(day: Day) { return day.payload.fills.length ? `${day.payload.fills.length} 笔模拟成交` : '无成交'; }
function metric(row: Metrics | null | undefined, field: keyof Metrics) { return row?.[field] as number | null | undefined; }
watch([market, key], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>

<template>
  <div
    class="page-shell min-w-0 space-y-5"
    data-testid="stock-strategies-page"
  >
    <PageHeader
      :title="detail?.strategy.name || (key ? '策略详情' : '策略模拟')"
      en="Stock Strategies"
      description="固定规则的独立模拟账户，每日盘后结算并生成下一交易日计划。"
    >
      <template #actions>
        <Button
          v-if="key"
          variant="ghost"
          as-child
        >
          <RouterLink :to="{ path: '/strategies', query: { market } }">
            <ArrowLeft class="size-4" />策略列表
          </RouterLink>
        </Button>
        <ResearchMarketToggle
          :model-value="market"
          data-testid="strategy-market-switcher"
          @update:model-value="setMarket"
        />
        <Button
          variant="outline"
          :disabled="loading"
          @click="load"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <Button
          v-if="currentUser?.role === 'admin'"
          :disabled="submitting || loading"
          @click="run"
        >
          {{ key ? '检查此策略' : '检查本市场' }}
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="taskId"
      role="status"
      class="text-sm text-muted-foreground"
    >
      任务已提交。<RouterLink
        class="underline"
        to="/tasks/runs"
      >
        查看执行记录
      </RouterLink>，完成后刷新此页。
    </p>
    <p class="text-sm text-muted-foreground">
      A股与美股资金独立；每策略初始100万本币。收盘信号于下一交易日开盘模拟成交，盘后确认；零手续费与滑点，允许碎股。20个结算日前不展示年化。
    </p>
    <p
      v-if="loading"
      role="status"
      class="rounded-lg border p-8 text-center text-muted-foreground"
    >
      正在读取策略账本…
    </p>
    <template v-if="overview">
      <div class="flex flex-wrap gap-3 text-sm">
        <Badge variant="secondary">
          {{ counts.total }} 个策略
        </Badge>
        <Badge
          v-if="counts.waiting"
          variant="outline"
        >
          {{ counts.waiting }} 个等待数据
        </Badge>
        <Badge
          v-if="counts.failed"
          variant="destructive"
        >
          {{ counts.failed }} 个运行失败
        </Badge>
      </div>
      <div class="min-w-0 overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="min-w-72">
                <BilingualLabel
                  zh="策略"
                  en="Strategy"
                  compact
                />
              </TableHead>
              <TableHead class="min-w-28">
                结算交易日
              </TableHead>
              <TableHead
                v-for="column in metricColumns"
                :key="column.key"
                class="min-w-28 text-right"
              >
                <BilingualLabel
                  :zh="column.zh"
                  :en="column.en"
                  compact
                />
              </TableHead>
              <TableHead class="min-w-48">
                运行状态
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in overview.items"
              :key="row.strategy.key"
              class="cursor-pointer"
              data-testid="strategy-row"
              @click="show(row.strategy.key)"
            >
              <TableCell class="font-medium">
                <RouterLink
                  :to="{ name: 'strategy-detail', params: { strategyKey: row.strategy.key }, query: { market } }"
                  class="inline-flex items-center gap-2 hover:underline"
                  @click.stop
                >
                  {{ row.strategy.name }}<ArrowUpRight class="size-4 shrink-0 text-muted-foreground" />
                </RouterLink><p class="mt-1 text-xs text-muted-foreground">
                  {{ row.strategy.slots }}仓 · {{ row.strategy.atr ? `ATR ${row.strategy.atr}` : '无ATR' }} · v{{ row.strategy.version }}
                </p>
              </TableCell>
              <TableCell>{{ row.latest?.tradeDate ?? '—' }}</TableCell>
              <TableCell
                v-for="column in metricColumns"
                :key="column.key"
                class="text-right tabular-nums"
                :class="column.key === 'exposure' ? '' : tone(metric(row.latest, column.key))"
              >
                {{ pct(metric(row.latest, column.key)) }}
              </TableCell>
              <TableCell>
                <Badge :variant="row.status === 'failed' ? 'destructive' : 'secondary'">
                  {{ statuses[row.status] }}
                </Badge><p
                  v-if="row.lastRun?.reason"
                  class="mt-2 max-w-80 whitespace-normal text-xs text-muted-foreground"
                >
                  {{ row.lastRun.tradeDate }}：{{ row.lastRun.reason }}
                </p>
              </TableCell>
            </TableRow>
            <TableRow v-if="!overview.items.length">
              <TableCell
                :colspan="8"
                class="p-10 text-center text-muted-foreground"
              >
                该市场尚无已启用策略。
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
      <p class="text-xs text-muted-foreground">
        表格展示每项最后成功结算日的收益；等待或失败时保留该日结果，错误日期单独标明。研究历史收益不计入本模块模拟。
      </p>
    </template>
    <template v-if="detail">
      <div
        v-if="detail.lastRun && detail.lastRun.status !== 'success'"
        role="alert"
        class="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
      >
        <strong>{{ detail.lastRun.status === 'failed' ? '策略运行失败' : '等待数据就绪' }} · {{ detail.lastRun.tradeDate }}</strong>
        <p class="mt-1">
          {{ detail.lastRun.reason }}
        </p><p class="mt-1 text-muted-foreground">
          最后成功结算：{{ latest?.tradeDate ?? '暂无' }}；已重试 {{ detail.lastRun.attempts }} 次。
        </p>
      </div>
      <p
        v-if="latest && detail.expectedDate && latest.tradeDate < detail.expectedDate && detail.lastRun?.status === 'success'"
        role="status"
        class="rounded-lg border p-4 text-sm text-muted-foreground"
      >
        正在等待补算至 {{ detail.expectedDate }}；当前收益截至 {{ latest.tradeDate }}。
      </p>
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div
          v-for="column in metricColumns"
          :key="column.key"
          class="rounded-lg border p-4"
        >
          <BilingualLabel
            :zh="column.zh"
            :en="column.en"
          /><p
            class="mt-2 text-2xl font-semibold tabular-nums"
            :class="column.key === 'exposure' ? '' : tone(metric(latest, column.key))"
          >
            {{ pct(metric(latest, column.key)) }}
          </p>
        </div>
      </div>
      <div class="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
        <span>起始交易日 {{ detail.startDate ?? '尚未启动' }}</span><span>最后结算 {{ latest?.tradeDate ?? '—' }}</span>
        <span>净值 {{ number(latest?.nav) }} {{ market === 'CN' ? 'CNY' : 'USD' }}</span><span>现金 {{ number(latest?.payload.cash) }}</span>
        <span>{{ latest?.payload.sessions ?? 0 }} 个结算日 / {{ latest?.payload.closedRounds ?? 0 }} 个完成回合</span>
      </div>
      <section class="rounded-lg border p-4">
        <h2 class="font-semibold">
          <BilingualLabel
            zh="收益与回撤"
            en="Performance & drawdown"
          />
        </h2>
        <PerformanceChart
          v-if="detail.curve.length"
          :items="detail.curve"
          :benchmark="market === 'CN' ? '沪深300ETF' : 'SPY'"
        />
        <p
          v-else
          class="p-10 text-center text-muted-foreground"
        >
          首次盘后结算后开始记录曲线，历史日线仅用于指标预热。
        </p>
      </section>
      <div class="grid min-w-0 gap-5 xl:grid-cols-2">
        <section class="min-w-0 rounded-lg border p-4">
          <h2 class="font-semibold">
            <BilingualLabel
              zh="当前模拟持仓"
              en="Simulated positions"
            />
          </h2>
          <div class="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>证券</TableHead><TableHead class="text-right">
                    股数
                  </TableHead><TableHead class="text-right">
                    成本
                  </TableHead><TableHead class="text-right">
                    估值
                  </TableHead><TableHead class="text-right">
                    ATR线
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="[code, pos] in positions"
                  :key="code"
                >
                  <TableCell>
                    <StockLink
                      :code="code"
                      :name="pos.name"
                      :market="market"
                    /><p
                      v-if="pos.pendingExit.length"
                      class="mt-1 text-xs text-destructive"
                    >
                      等待卖出：{{ pos.pendingExit.join('；') }}
                    </p>
                  </TableCell><TableCell class="text-right tabular-nums">
                    {{ number(pos.quantity, 4) }}
                  </TableCell><TableCell class="text-right tabular-nums">
                    {{ number(pos.entryPrice, 4) }}
                  </TableCell><TableCell class="text-right tabular-nums">
                    {{ number(pos.mark, 4) }}<p class="text-xs text-muted-foreground">
                      {{ pos.markDate }}
                    </p>
                  </TableCell><TableCell class="text-right tabular-nums">
                    {{ number(pos.stop, 4) }}
                  </TableCell>
                </TableRow>
                <TableRow v-if="!positions.length">
                  <TableCell
                    :colspan="5"
                    class="py-8 text-center text-muted-foreground"
                  >
                    当前空仓
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
          <p
            v-for="warning in latest?.payload.warnings ?? []"
            :key="warning"
            class="mt-2 text-sm text-destructive"
          >
            {{ warning }}
          </p>
        </section>
        <section class="min-w-0 rounded-lg border p-4">
          <h2 class="font-semibold">
            <BilingualLabel
              zh="下一交易日计划"
              en="Next session plan"
            />
          </h2>
          <template v-if="nextPlan">
            <p class="mt-3 text-sm">
              {{ nextPlan.signalDate }} 收盘信号 → {{ nextPlan.executionDate }} 开盘
            </p>
            <p
              v-if="latest?.payload.nextIsHistorical"
              class="mt-2 text-sm text-destructive"
            >
              历史补算计划，生成时该开盘已过去，请勿作为当前待执行计划。
            </p>
            <p
              v-if="nextPlan.status === 'PAUSED'"
              class="mt-2 text-sm text-destructive"
            >
              账户暂停新增，剩余 {{ latest?.payload.pauseRemaining }} 个开盘；未完成卖出持续等待。
            </p>
            <ul class="mt-3 space-y-2 text-sm">
              <li
                v-for="(reasons, code) in nextPlan.exits"
                :key="code"
              >
                <template v-if="reasons.length">
                  <strong>卖出 {{ code }}</strong>：{{ reasons.join('；') }}
                </template>
              </li>
            </ul>
            <p class="mt-3 text-sm text-muted-foreground">
              候选按优先级排列，开盘仅在有空位、现金及可成交条件下买入：
            </p>
            <div
              v-if="nextPlan.candidates.length"
              class="mt-2 flex flex-wrap gap-2"
            >
              <Badge
                v-for="(candidate, index) in nextPlan.candidates.slice(0, 10)"
                :key="candidate.code"
                variant="outline"
              >
                {{ index + 1 }}. {{ candidate.name }} · {{ candidate.code }}
              </Badge>
            </div>
            <p
              v-else
              class="mt-3 text-sm text-muted-foreground"
            >
              无新增候选。
            </p>
            <p
              v-if="nextPlan.candidates.length > 10"
              class="mt-2 text-xs text-muted-foreground"
            >
              共 {{ nextPlan.candidates.length }} 个候选，此处展示前10个。
            </p>
          </template><p
            v-else
            class="py-8 text-center text-muted-foreground"
          >
            尚无收盘计划
          </p>
        </section>
      </div>
      <section class="rounded-lg border p-4">
        <h2 class="font-semibold">
          <BilingualLabel
            zh="策略规则与元数据"
            en="Rules & metadata"
          />
        </h2>
        <div class="mt-4 grid gap-x-8 gap-y-5 lg:grid-cols-2">
          <div
            v-for="rule in detail.strategy.rules"
            :key="rule.label"
            class="min-w-0"
          >
            <h3 class="text-sm font-medium">
              {{ rule.label }}
            </h3><p class="mt-1 break-words text-sm leading-relaxed text-muted-foreground">
              {{ rule.text }}
            </p>
          </div>
        </div>
        <p
          v-if="detail.universe"
          class="mt-5 break-all text-xs text-muted-foreground"
        >
          冻结股票 {{ detail.universe.stocks.length }} / ETF {{ detail.universe.etfs.length }} / 广度分母池 {{ detail.universe.breadth.length }}；版本 v{{ detail.strategy.version }}；范围哈希 {{ detail.universe.hash }}
        </p>
      </section>
      <section class="min-w-0 rounded-lg border p-4">
        <h2 class="font-semibold">
          <BilingualLabel
            zh="每日账本"
            en="Daily ledger"
          />
        </h2>
        <div class="mt-3 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead class="min-w-28">
                  交易日
                </TableHead><TableHead class="text-right">
                  当日收益
                </TableHead><TableHead class="text-right">
                  净值
                </TableHead><TableHead class="min-w-80">
                  操作与依据
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="day in detail.days"
                :key="day.tradeDate"
              >
                <TableCell>
                  {{ day.tradeDate }}<Badge
                    v-if="day.payload.replayed"
                    variant="outline"
                    class="mt-1"
                  >
                    补算
                  </Badge>
                </TableCell><TableCell
                  class="text-right tabular-nums"
                  :class="tone(day.dailyReturn)"
                >
                  {{ pct(day.dailyReturn) }}
                </TableCell><TableCell class="text-right tabular-nums">
                  {{ number(day.nav) }}
                </TableCell><TableCell>
                  <details>
                    <summary class="cursor-pointer text-sm">
                      {{ dayAction(day) }} · 查看成交、计划与数据
                    </summary>
                    <div class="mt-3 space-y-2 text-sm">
                      <p
                        v-for="(fill, index) in day.payload.fills"
                        :key="index"
                      >
                        {{ fill.action === 'BUY' ? '买入' : '卖出' }} {{ fill.name }}（{{ fill.code }}）{{ number(fill.quantity, 4) }} 股 × {{ number(fill.price, 4) }}；信号 {{ fill.signalDate }}；{{ fill.reasons.join('；') }}
                      </p>
                      <p
                        v-for="(block, index) in day.payload.blocked"
                        :key="`b${index}`"
                      >
                        未成交 {{ block.code }}：{{ block.reason }}
                      </p>
                      <p
                        v-for="(change, index) in day.payload.adjustments"
                        :key="`a${index}`"
                      >
                        复权换算 {{ change.code }}：{{ change.scale }}；{{ change.reason }}
                      </p>
                      <p>次开盘 {{ day.payload.plan.executionDate }}，{{ day.payload.plan.status === 'PAUSED' ? '暂停新增' : '按候选依序填仓' }}；候选 {{ day.payload.plan.candidates.map(r => r.code).join('、') || '无' }}</p>
                      <p
                        v-for="(reasons, code) in day.payload.plan.exits"
                        :key="code"
                      >
                        <template v-if="reasons.length">
                          计划卖出 {{ code }}：{{ reasons.join('；') }}
                        </template>
                      </p>
                      <p v-if="day.payload.breadth != null">
                        MA50广度 {{ pct(day.payload.breadth) }}，合格分母 {{ day.payload.breadthDenominator }}
                      </p>
                      <p
                        v-for="warning in day.payload.warnings"
                        :key="warning"
                        class="text-destructive"
                      >
                        {{ warning }}
                      </p>
                      <p class="text-xs text-muted-foreground">
                        计算时间 {{ formatDateTime(day.payload.computedAt) }}；数据窗口 {{ day.payload.provenance.windowStart }} — {{ day.payload.provenance.windowEnd }}
                      </p>
                    </div>
                  </details>
                </TableCell>
              </TableRow><TableRow v-if="!detail.days.length">
                <TableCell
                  :colspan="4"
                  class="py-8 text-center text-muted-foreground"
                >
                  尚无每日结算记录
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <Button
          v-if="detail.nextBefore"
          class="mt-4"
          variant="outline"
          :disabled="moreLoading"
          @click="loadMore"
        >
          {{ moreLoading ? '读取中…' : '加载更早记录' }}
        </Button>
      </section>
    </template>
  </div>
</template>
