<script lang="ts">
// Shell keys routed views by path; keep list offsets across detail remounts.
const listScroll = new Map<string, number>();
</script>
<script setup lang="ts">
import { formatPercent } from '@/utils/number';
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import { ArrowLeft, ArrowUpRight, RefreshCcw } from 'lucide-vue-next';
import PageHeader from '@/components/layout/PageHeader.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import PositionsPlan from '@/components/stock-strategies/PositionsPlan.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Skeleton } from '@/components/ui/skeleton';
import { tasksApi } from '@/api/tasks';
import { finite, runStatus, strategyTags } from '@/utils/stockStrategies';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
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

const statuses = { success: '已结算', waiting: '等待数据', failed: '运行失败', not_started: '尚未启动', catching_up: '等待补算' };
const pct = (v: number | null | undefined) => formatPercent(v, { digits: 2, signed: true });
const number = (v: number | undefined | null, digits = 2) => !finite(v) ? '—' : v.toLocaleString('zh-CN', { maximumFractionDigits: digits });
const tone = (v: number | undefined | null) => v == null || v === 0 ? '' : v > 0 ? 'text-market-up' : 'text-market-down';
const metricColumns = [
  { key: 'totalReturn', zh: '累计收益', en: 'Total return' }, { key: 'maxDrawdown', zh: '最大回撤 · 风险', en: 'Max drawdown' },
  { key: 'dailyReturn', zh: '结算日收益', en: 'Daily return' }, { key: 'exposure', zh: '持仓比例', en: 'Exposure' },
  { key: 'cagr', zh: '复合年化', en: 'CAGR' },
] as const;
const tab = ref('positions');
const search = computed({ get: () => String(route.query.search ?? ''), set: value => updateQuery('search', value) });
const status = computed({ get: () => String(route.query.status ?? ''), set: value => updateQuery('status', value) });
const sort = computed({ get: () => String(route.query.sort ?? 'default'), set: value => updateQuery('sort', value) });
const ledgerDate = ref(''); const ledgerAction = ref('');
const taskStatus = ref('');
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let objectId = '';
let contextGeneration = 0;
function updateQuery(field: string, value: string) {
  void router.replace({ query: { ...route.query, [field]: value || undefined } });
}
const statusOptions = [{ value: '', label: '全部状态' }, ...Object.entries(statuses).map(([value, label]) => ({ value, label }))];
const sortOptions = [{ value: 'default', label: '默认顺序' }, { value: 'return_desc', label: '累计收益：高到低' },
  { value: 'return_asc', label: '累计收益：低到高' }, { value: 'drawdown_asc', label: '最大回撤：小到大' }, { value: 'drawdown_desc', label: '最大回撤：大到小' }];
const counts = computed(() => Object.fromEntries(Object.keys(statuses).map(s => [s, overview.value?.items.filter(r => r.status === s).length ?? 0])));
const filteredItems = computed(() => {
  const items = (overview.value?.items ?? []).filter(r => r.strategy.name.toLowerCase().includes(search.value.trim().toLowerCase()) && (!status.value || r.status === status.value));
  return items.sort((a, b) => {
    if (sort.value === 'default') return 0;
    const drawdown = sort.value.startsWith('drawdown');
    const av = a.latest?.[drawdown ? 'maxDrawdown' : 'totalReturn'];
    const bv = b.latest?.[drawdown ? 'maxDrawdown' : 'totalReturn'];
    if (!finite(av)) return finite(bv) ? 1 : 0;
    if (!finite(bv)) return -1;
    return (drawdown ? Math.abs(av) - Math.abs(bv) : av - bv) * (sort.value.endsWith('desc') ? -1 : 1);
  });
});
const datesDiffer = computed(() => new Set(overview.value?.items.map(r => r.latest?.tradeDate ?? '未结算')).size > 1);
const ledgerDays = computed(() => (detail.value?.days ?? []).filter(day => (!ledgerDate.value || day.tradeDate === ledgerDate.value)
  && (!ledgerAction.value || (ledgerAction.value === 'blocked' ? day.payload.blocked.length > 0
    : ledgerAction.value === 'none' ? !day.payload.fills.length : day.payload.fills.some(f => f.action === ledgerAction.value)))));
const unsignedPct = (v: number | null | undefined) => formatPercent(v, { digits: 2, signed: false });
const metricText = (row: Metrics | null | undefined, field: keyof Metrics) => field === 'exposure' || field === 'maxDrawdown'
  ? unsignedPct(metric(row, field)) : pct(metric(row, field));
const metricTone = (row: Metrics | null | undefined, field: keyof Metrics) => field === 'exposure' ? ''
  : field === 'maxDrawdown' ? 'text-amber-700 dark:text-amber-400' : tone(metric(row, field));
async function load() {
  const token = ++generation; loading.value = true; error.value = null; moreLoading.value = false;
  const id = `${market.value}/${key.value}`;
  const changed = objectId !== id;
  if (changed) {
    ++contextGeneration; submitting.value = false;
    objectId = id; overview.value = null; detail.value = null; taskId.value = ''; taskStatus.value = '';
    clearTimeout(pollTimer); tab.value = 'positions'; ledgerDate.value = ''; ledgerAction.value = '';
  }
  try {
    if (key.value) {
      const response = await api.detail(key.value, market.value);
      if (token === generation) detail.value = response;
    } else {
      const response = await api.overview(market.value);
      if (token === generation) {
        overview.value = response;
      }
    }
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally {
    if (token === generation) {
      loading.value = false;
      // Restore after the refresh status is removed, otherwise scroll anchoring shifts the offset.
      if (changed && !key.value && overview.value) {
        await nextTick();
        if (token === generation) window.scrollTo(0, listScroll.get(market.value) ?? 0);
      }
    }
  }
}
async function loadMore() {
  if (!detail.value?.nextBefore || moreLoading.value || loading.value) return;
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
function rememberList() { listScroll.set(market.value, window.scrollY); }
function show(strategyKey: string) { rememberList(); void router.push({ name: 'strategy-detail', params: { strategyKey }, query: { ...route.query, market: market.value } }); }
async function run() {
  const owner = contextGeneration; submitting.value = true; error.value = null;
  try {
    const result = await api.run(market.value, key.value || undefined);
    if (owner === contextGeneration) { clearTimeout(pollTimer); taskId.value = result.taskId; taskStatus.value = '排队中'; void pollTask(result.taskId, owner); }
  } catch (cause) { if (owner === contextGeneration) error.value = getParsedApiError(cause); }
  finally { if (owner === contextGeneration) submitting.value = false; }
}
async function pollTask(id: string, owner: number) {
  try {
    const task = await tasksApi.getTaskRunDetail(id);
    if (owner !== contextGeneration || id !== taskId.value) return;
    const labels: Record<string, string> = { pending: '排队中', processing: '执行中', retrying: '重试中', completed: '检查完成', partial: '部分完成', failed: '检查失败', skipped: '已跳过', cancelled: '已取消' };
    taskStatus.value = labels[task.status] ?? task.status;
    if (['completed', 'partial', 'failed', 'skipped', 'cancelled'].includes(task.status)) { await load(); return; }
    pollTimer = setTimeout(() => { void pollTask(id, owner); }, 3000);
  } catch { if (owner === contextGeneration && id === taskId.value) taskStatus.value = '暂时无法读取任务状态，请到任务中心查看或刷新'; }
}
function dayAction(day: Day) {
  return `买入 ${day.payload.fills.filter(f => f.action === 'BUY').length} · 卖出 ${day.payload.fills.filter(f => f.action === 'SELL').length} · 未成交 ${day.payload.blocked.length}`;
}
function metric(row: Metrics | null | undefined, field: keyof Metrics) { return row?.[field] as number | null | undefined; }
watch([market, key], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; ++contextGeneration; objectId = ''; clearTimeout(pollTimer); });
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
          <RouterLink :to="{ path: '/strategies', query: { ...route.query, market } }">
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
          :disabled="submitting || loading || ['排队中', '执行中', '重试中'].includes(taskStatus)"
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
      {{ taskStatus }}。<RouterLink
        class="underline"
        to="/tasks/runs"
      >
        查看执行记录
      </RouterLink>，检查结束后自动刷新。检查任务结束不代表每项策略均已结算。
    </p>
    <p class="text-sm text-muted-foreground">
      A股与美股资金独立；每策略初始100万本币。无开盘下单或盘中执行任务；盘后按此前冻结计划及开盘价模拟结算。零手续费与滑点，允许碎股。20个结算日前不展示年化。
    </p>
    <div
      v-if="loading && !overview && !detail"
      role="status"
      aria-label="正在读取策略账本"
      class="grid gap-4 md:grid-cols-2"
    >
      <Skeleton
        v-for="n in 4"
        :key="n"
        class="h-48 rounded-xl"
      />
    </div>
    <p
      v-else-if="loading"
      role="status"
      class="text-sm text-muted-foreground"
    >
      正在刷新，保留上次成功读取的内容…
    </p>
    <template v-if="overview">
      <section class="rounded-xl border bg-card p-5">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p class="text-sm text-muted-foreground">
              独立模拟账户 · {{ market === 'CN' ? 'A股 / CNY' : '美股 / USD' }}
            </p><h2 class="mt-1 text-2xl font-semibold">
              {{ overview.items.length }} 个策略持续观察
            </h2>
          </div>
          <p class="text-sm text-muted-foreground">
            参考交易日 {{ overview.expectedDate ?? '未提供' }} · 不汇总独立账户资产或收益
          </p>
        </div>
        <div class="mt-5 flex flex-wrap gap-2">
          <Button
            :variant="!status ? 'default' : 'outline'"
            size="sm"
            @click="status = ''"
          >
            全部 {{ overview.items.length }}
          </Button>
          <Button
            v-for="(label, value) in statuses"
            :key="value"
            :variant="status === value ? 'default' : 'outline'"
            size="sm"
            @click="status = value"
          >
            {{ label }} {{ counts[value] }}
          </Button>
        </div>
        <p
          v-if="datesDiffer"
          class="mt-3 text-sm text-amber-700 dark:text-amber-400"
        >
          结算日期不一致：收益观察区间不同，请核对日期后比较。
        </p>
      </section>
      <div class="grid gap-3 sm:grid-cols-3">
        <FieldInput
          v-model="search"
          label="搜索策略名称"
          placeholder="输入策略名称"
        />
        <FieldSelect
          v-model="status"
          label="运行状态"
          :options="statusOptions"
        />
        <FieldSelect
          v-model="sort"
          label="排序"
          :options="sortOptions"
        />
      </div>
      <div class="grid min-w-0 gap-4 lg:grid-cols-2">
        <article
          v-for="row in filteredItems"
          :key="row.strategy.key"
          class="min-w-0 rounded-xl border bg-card p-5 transition-colors hover:border-foreground/30"
          data-testid="strategy-row"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <RouterLink
                :to="{ name: 'strategy-detail', params: { strategyKey: row.strategy.key }, query: { ...route.query, market } }"
                class="text-lg font-semibold hover:underline"
                @click="rememberList"
              >
                {{ row.strategy.name }}<ArrowUpRight class="ml-1 inline size-4" />
              </RouterLink>
              <p class="mt-2 text-xs leading-relaxed text-muted-foreground">
                {{ strategyTags(row.strategy) }}
              </p>
            </div>
            <Badge
              :variant="row.status === 'failed' ? 'destructive' : 'secondary'"
              class="shrink-0"
            >
              {{ statuses[row.status] }}
            </Badge>
          </div>
          <div class="my-5 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div
              v-for="field in (['totalReturn', 'maxDrawdown', 'dailyReturn'] as const)"
              :key="field"
            >
              <p class="text-xs text-muted-foreground">
                {{ field === 'totalReturn' ? '累计收益' : field === 'maxDrawdown' ? '最大回撤 · 风险' : '结算日收益' }}
              </p>
              <p
                class="mt-1 text-xl font-semibold tabular-nums"
                :class="metricTone(row.latest, field)"
              >
                {{ metricText(row.latest, field) }}
              </p>
            </div>
          </div>
          <div class="flex justify-between text-xs text-muted-foreground">
            <span>持仓比例 {{ unsignedPct(row.latest?.exposure) }}</span><span>最多 {{ row.strategy.slots }} 仓</span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              class="h-full bg-foreground/50"
              :style="{ width: `${Math.max(0, Math.min(100, (row.latest?.exposure ?? 0) * 100))}%` }"
            />
          </div>
          <div class="mt-4 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
            <span>最后结算 {{ row.latest?.tradeDate ?? '尚未结算' }}</span><span>起点 {{ row.startDate ?? '未启动' }} · v{{ row.strategy.version }}</span>
          </div>
          <p
            v-if="overview.expectedDate && row.latest && row.latest.tradeDate < overview.expectedDate"
            class="mt-2 text-xs text-amber-700 dark:text-amber-400"
          >
            结算滞后于参考交易日 {{ overview.expectedDate }}，当前收益仍截至 {{ row.latest.tradeDate }}。
          </p>
          <details
            v-if="row.lastRun?.reason"
            class="mt-3 rounded bg-muted/50 p-2 text-xs"
          >
            <summary class="cursor-pointer break-words">
              {{ row.lastRun.tradeDate }}：{{ row.lastRun.reason.slice(0, 80) }}{{ row.lastRun.reason.length > 80 ? '…（展开完整原因）' : '（展开）' }}
            </summary><p class="mt-2 whitespace-pre-wrap break-words">
              {{ row.lastRun.reason }}
            </p>
          </details>
          <Button
            variant="ghost"
            size="sm"
            class="mt-3"
            @click="show(row.strategy.key)"
          >
            查看持仓、计划与规则 <ArrowUpRight class="size-4" />
          </Button>
        </article>
      </div>
      <p
        v-if="!filteredItems.length"
        class="rounded-lg border p-10 text-center text-muted-foreground"
      >
        {{ overview.items.length ? '没有符合筛选条件的策略，请调整搜索或状态。' : '该市场尚无已启用策略。' }}
      </p>
      <p class="text-xs text-muted-foreground">
        每项展示最后成功结算结果；等待或失败时保留该日收益。研究历史收益不计入本模块；历史补算不代表当时按时执行。
      </p>
    </template>
    <template v-if="detail">
      <section class="rounded-xl border bg-card p-5">
        <div class="flex flex-wrap items-center gap-3">
          <Badge :variant="runStatus(detail) === 'failed' ? 'destructive' : 'secondary'">
            {{ statuses[runStatus(detail)] }}
          </Badge><span class="text-sm">最后成功结算 {{ latest?.tradeDate ?? '尚无' }}</span>
        </div>
        <p class="mt-3 text-sm leading-relaxed">
          {{ detail.strategy.rules?.[0]?.text }}
        </p>
        <p class="mt-2 text-xs text-muted-foreground">
          {{ strategyTags(detail.strategy) }}
        </p>
        <p
          v-if="latest"
          class="mt-2 text-xs text-muted-foreground"
        >
          实际计算时间 {{ formatDateTime(latest.payload.computedAt) }} · {{ latest.payload.replayed ? '历史补算记录' : '未标记补算（不代表按时执行认证）' }}
        </p>
      </section>
      <div
        v-if="detail.lastRun && detail.lastRun.status !== 'success'"
        role="alert"
        class="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
      >
        <strong>{{ detail.lastRun.status === 'failed' ? '策略运行失败' : '等待数据就绪' }} · {{ detail.lastRun.tradeDate }}</strong>
        <p class="mt-1">
          {{ detail.lastRun.reason }}
        </p><p class="mt-1 text-muted-foreground">
          最后成功结算：{{ latest?.tradeDate ?? '暂无' }}；累计尝试 {{ detail.lastRun.attempts }} 次。
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
            :class="metricTone(latest, column.key)"
          >
            {{ metricText(latest, column.key) }}
          </p>
          <p
            v-if="column.key === 'cagr'"
            class="mt-2 text-xs text-muted-foreground"
          >
            观察 {{ latest?.payload.sessions ?? 0 }} 个结算日；{{ (latest?.payload.sessions ?? 0) < 20 ? '不足20个结算日，暂不展示年化' : latest?.cagr == null ? '年化计算不可用' : '按实际日历时长年化，短期值可能不稳定' }}
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
      <nav
        class="flex flex-wrap gap-2"
        aria-label="策略详情内容"
      >
        <Button
          v-for="item in [{ value: 'positions', label: '持仓与计划' }, { value: 'ledger', label: '每日账本' }, { value: 'rules', label: '策略规则' }]"
          :key="item.value"
          :variant="tab === item.value ? 'default' : 'outline'"
          :aria-pressed="tab === item.value"
          @click="tab = item.value"
        >
          {{ item.label }}
        </Button>
      </nav>
      <PositionsPlan
        v-if="tab === 'positions'"
        :key="objectId"
        :detail="detail"
      />
      <section
        v-if="tab === 'rules'"
        class="rounded-lg border p-4"
      >
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
        <details
          v-if="detail.universe"
          class="mt-5 break-all text-xs text-muted-foreground"
        >
          <summary class="cursor-pointer">
            技术元数据
          </summary><p class="mt-2">
            冻结股票 {{ detail.universe.stocks.length }} / ETF {{ detail.universe.etfs.length }} / 广度分母池 {{ detail.universe.breadth.length }}；版本 v{{ detail.strategy.version }}；范围哈希 {{ detail.universe.hash }}；研究来源 {{ detail.strategy.sourceId }}；风控版本 {{ detail.strategy.riskEngine }}
          </p>
        </details>
        <p class="mt-4 text-sm text-muted-foreground">
          同一交易日只成功结算一次；调度检查、重试或补算不代表重复成交。T日收盘冻结排名，T+1盘后仅用原计划模拟T+1开盘成交，绝不使用T+1新排名倒选。可成交仅为有效开盘价与部分A股涨跌停的简化判断，不模拟完整流动性、价差或部分成交。
        </p>
      </section>
      <section
        v-if="tab === 'ledger'"
        class="min-w-0 rounded-lg border p-4"
      >
        <h2 class="font-semibold">
          <BilingualLabel
            zh="每日账本"
            en="Daily ledger"
          />
        </h2>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <FieldInput
            v-model="ledgerDate"
            label="结算日期"
            type="date"
          /><FieldSelect
            v-model="ledgerAction"
            label="成交情况"
            :options="[{ value: '', label: '全部' }, { value: 'BUY', label: '有买入' }, { value: 'SELL', label: '有卖出' }, { value: 'blocked', label: '有未成交' }, { value: 'none', label: '无成交' }]"
          />
        </div>
        <p class="mt-2 text-xs text-muted-foreground">
          仅筛选已加载的 {{ detail.days.length }} 条记录；更早日期请继续加载。未成交数仅为引擎记录的开盘受阻事件，不是全部未买候选数。补算收益不代表当时按时执行。
        </p>
        <div class="mt-3 space-y-3">
          <article
            v-for="day in ledgerDays"
            :key="day.tradeDate"
            class="rounded-lg border p-4"
          >
            <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
              <div class="flex items-center gap-2">
                <strong>{{ day.tradeDate }}</strong><Badge
                  v-if="day.payload.replayed"
                  variant="outline"
                >
                  补算
                </Badge>
              </div>
              <div class="flex flex-wrap gap-4">
                <span>当日收益 <span :class="tone(day.dailyReturn)">{{ pct(day.dailyReturn) }}</span></span><span>净值 {{ number(day.nav) }}</span>
              </div>
            </div>
            <details class="mt-3">
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
                <p
                  v-if="day.payload.nextIsHistorical"
                  class="text-destructive"
                >
                  历史补算计划：生成时已错过执行开盘，非当前待执行计划。
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
          </article>
          <p
            v-if="!ledgerDays.length"
            class="py-8 text-center text-muted-foreground"
          >
            {{ detail.days.length ? '已加载记录中无匹配结果' : '尚无每日结算记录' }}
          </p>
        </div>
        <Button
          v-if="detail.nextBefore"
          class="mt-4"
          variant="outline"
          :disabled="moreLoading || loading"
          @click="loadMore"
        >
          {{ moreLoading ? '读取中…' : '加载更早记录' }}
        </Button>
      </section>
    </template>
  </div>
</template>
