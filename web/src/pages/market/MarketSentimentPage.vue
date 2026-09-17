<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { marketSentimentApi as api, type Overview, type History, type Pool, type Ladder } from '@/api/marketSentiment';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import SentimentCharts from '@/components/market-sentiment/SentimentCharts.vue';
import PoolTable from '@/components/market-sentiment/PoolTable.vue';
import { stateLabels, boards, pct, money, delta } from '@/components/market-sentiment/display';
import { formatDateTime } from '@/utils/format';
const { currentUser } = useAuth();
const overview = shallowRef<Overview | null>(null);
const history = shallowRef<History>({ dates: [], items: [] });
const pool = shallowRef<Pool | null>(null); const ladder = shallowRef<Ladder | null>(null);
const date = ref(''); const dates = ref<string[]>([]); const loading = ref(false); const poolLoading = ref(false);
const error = shallowRef<ParsedApiError | null>(null); const poolError = shallowRef<ParsedApiError | null>(null);
const auxiliaryError = shallowRef<ParsedApiError | null>(null); const runError = shallowRef<ParsedApiError | null>(null);
const view = ref('full'); const kind = ref('limit_up'); const scope = ref('main'); const board = ref('');
const q = ref(''); const reason = ref(''); const page = ref(1); const submitting = ref(false); const taskId = ref('');
let generation = 0; let poolGeneration = 0;
const row = computed(() => overview.value?.observation ?? null);
const cards = computed(() => [
  { label: '涨停参与度', value: row.value?.limitUpCount, change: row.value?.changes.limitUpCount },
  { label: '首板', value: row.value?.firstBoardCount, change: row.value?.changes.firstBoardCount },
  { label: '连板接力', value: row.value?.multiBoardCount, change: row.value?.changes.multiBoardCount },
  { label: '最高连续板', value: row.value?.highestBoard, change: row.value?.changes.highestBoard },
]);
const promotionLabels: Record<string, string> = { '1To2': '1→2', '2To3': '2→3', '3To4': '3→4', multi: '连板总体' };
const sourceLabels: Record<string, string> = { limitDown: '跌停池', limitBreak: '炸板池', ladder: '官方天梯' };
const officialDates = computed(() => [...(ladder.value?.source?.window.dateList ?? [])].sort());
const poolLabels = computed(() => ({ limit_up: '涨停池', limit_down: `跌停池 · 上游全池 ${row.value?.supplements.limitDown?.total ?? '未获取'}`, limit_break: `炸板池 · 上游全池 ${row.value?.supplements.limitBreak?.total ?? '未获取'}` }));
const officialBoards: Record<string, string> = { twoBoard: '2板', threeBoard: '3板', fourBoard: '4板', fiveBoard: '5板', sixBoard: '6板', sevenOver: '7+板' };
async function loadPool() {
  const token = ++poolGeneration; poolLoading.value = true; poolError.value = null; pool.value = null;
  try {
    const result = await api.pool({ trade_date: date.value || overview.value?.tradeDate || undefined, kind: kind.value, board: board.value || undefined, q: q.value, reason: reason.value || undefined, scope: scope.value, page: page.value });
    if (token === poolGeneration) pool.value = result;
  } catch (cause) { if (token === poolGeneration) poolError.value = getParsedApiError(cause); }
  finally { if (token === poolGeneration) poolLoading.value = false; }
}
async function load(keepHistory = false) {
  const token = ++generation; ++poolGeneration; loading.value = true; error.value = null; auxiliaryError.value = null;
  overview.value = null; pool.value = null; ladder.value = null; board.value = ''; reason.value = ''; page.value = 1;
  if (!keepHistory) history.value = { dates: [], items: [] };
  try {
    const result = await api.overview(date.value || undefined); if (token !== generation) return;
    overview.value = result;
    const selected = date.value || result.tradeDate || undefined;
    await Promise.allSettled([
      loadPool(),
      api.ladder(selected).then(value => { if (token === generation) ladder.value = value; }).catch(cause => { if (token === generation) auxiliaryError.value = getParsedApiError(cause); }),
      ...(keepHistory ? [] : [api.history(selected).then(value => { if (token === generation) history.value = value; }).catch(cause => { if (token === generation) auxiliaryError.value = getParsedApiError(cause); })]),
    ]);
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function selectDate(value: string) { date.value = value; void load(true); }
function filterBoard(value: string) { kind.value = 'limit_up'; board.value = board.value === value ? '' : value; page.value = 1; void loadPool(); }
function filterReason(value: string) { kind.value = 'limit_up'; reason.value = value; page.value = 1; void loadPool(); }
function filterKind(value: string) { kind.value = value; board.value = ''; reason.value = ''; page.value = 1; void loadPool(); }
async function submit(backfill = false) {
  submitting.value = true; runError.value = null; taskId.value = '';
  try { taskId.value = (await api.run(backfill ? { backfill_days: 31, missing_only: true } : { trade_date: date.value || undefined })).taskId; }
  catch (cause) { runError.value = getParsedApiError(cause); }
  finally { submitting.value = false; }
}
onMounted(() => {
  void load();
  void api.dates().then(value => { dates.value = value; }).catch(cause => { auxiliaryError.value = getParsedApiError(cause); });
});
onBeforeUnmount(() => { generation++; poolGeneration++; });
</script>
<template>
  <div
    class="space-y-5"
    data-testid="market-sentiment-page"
  >
    <PageHeader
      title="市场情绪"
      description="Market Sentiment · A 股盘后观察 · 涨停参与度与连板接力"
    >
      <template #actions>
        <div class="flex items-center gap-2">
          <AppDatePicker
            v-model="date"
            class="w-48"
            placeholder="最新盘后结果"
            data-testid="sentiment-date"
            @update:model-value="load()"
          />
          <Button
            variant="outline"
            :disabled="loading"
            @click="load()"
          >
            刷新已有结果
          </Button>
        </div>
      </template>
    </PageHeader>
    <p class="text-xs leading-6 text-muted-foreground">
      主观察口径固定为非 ST 且非未开板新股；未开板新股按上游标记。热度描述涨停参与度与连板活跃度，不代表胜率、仓位或买卖建议，与 ETF Market Regime 独立。数据源：同花顺金融数据 API / 扶摇。
    </p>
    <div
      v-if="currentUser?.role === 'admin'"
      class="flex items-center gap-3 rounded-lg border p-3 text-sm"
    >
      <Button
        variant="outline"
        :disabled="submitting"
        @click="submit()"
      >
        计算所选完整交易日
      </Button>
      <Button
        variant="outline"
        :disabled="submitting"
        @click="submit(true)"
      >
        补最近31交易日缺失数据
      </Button>
      <span class="text-muted-foreground">异步执行；已保存 {{ dates.length }} 日</span>
      <RouterLink
        v-if="taskId"
        to="/tasks/runs"
        class="underline"
      >
        已提交 {{ taskId }} · 查看任务
      </RouterLink>
    </div>
    <AppApiErrorAlert
      v-if="runError"
      :error="runError"
      @dismiss="runError = null"
    />
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load()"
      @dismiss="error = null"
    />
    <AppApiErrorAlert
      v-if="auxiliaryError"
      :error="auxiliaryError"
      action-label="重试历史及天梯"
      @action="load()"
      @dismiss="auxiliaryError = null"
    />
    <Skeleton
      v-if="loading"
      class="h-32"
    />
    <p
      v-if="overview && !row"
      class="rounded-lg border p-8 text-center text-muted-foreground"
      data-testid="sentiment-empty"
    >
      {{ date || '最新' }} 暂无已保存盘后结果；页面查询不会触发取数。
    </p>
    <template v-if="row">
      <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span>数据有效日期 {{ row.tradeDate }}</span><span>生成 {{ formatDateTime(row.generatedAt) }}</span><span>源就绪 {{ formatDateTime(row.sourceTimestamp) }}</span><span>抓取 {{ formatDateTime(row.fetchedAt) }}</span>
      </div>
      <p
        v-if="!date && overview?.tradeDate !== overview?.expectedTradeDate"
        class="rounded-lg border border-amber-500/40 p-3 text-sm text-amber-600"
      >
        最新完整交易日应为 {{ overview?.expectedTradeDate }}，当前结果尚未更新。
      </p>
      <p
        v-if="Object.keys(row.quality.optionalErrors ?? {}).length"
        class="rounded-lg border border-amber-500/40 p-3 text-sm text-amber-600"
      >
        局部未获取：{{ Object.keys(row.quality.optionalErrors ?? {}).map(k => sourceLabels[k] ?? k).join('、') }}。补充来源不参与热度评分。
      </p>
      <p
        v-if="!row.scopeComplete || !row.boardsComplete"
        class="rounded-lg border border-amber-500/40 p-3 text-sm text-amber-600"
      >
        口径标记未知 {{ row.unknownScopeCount }} 只；连续性未确认 {{ row.unconfirmedBoardCount }} 只。受影响指标保留缺失，不按零计算。
      </p>
      <section class="grid grid-cols-[1.3fr_2fr] gap-4">
        <div class="rounded-xl border bg-muted/30 p-5">
          <p class="text-xs text-muted-foreground">
            FA 情绪观察 · {{ row.ruleVersion }}
          </p>
          <div class="my-3 flex items-baseline gap-5">
            <h2 class="text-3xl font-semibold">
              {{ stateLabels[row.state] }}
            </h2><span class="text-2xl tabular-nums">{{ row.heatScore?.toFixed(1) ?? '—' }}<small class="ml-1 text-xs text-muted-foreground">/ 100 热度</small></span>
          </div>
          <p
            v-for="r in row.stateReasons"
            :key="r"
            class="text-sm leading-6"
          >
            {{ r }}
          </p>
          <p class="mt-2 text-xs text-muted-foreground">
            {{ delta(row.changes.heatScore) }} · 历史基准：此前20个完整交易日，不含当日
          </p>
        </div>
        <div class="grid grid-cols-4 rounded-xl border p-5">
          <div
            v-for="card in cards"
            :key="card.label"
          >
            <p class="text-sm text-muted-foreground">
              {{ card.label }}
            </p><p class="my-3 text-3xl tabular-nums">
              {{ card.value ?? '—' }}
            </p><p class="text-xs text-muted-foreground">
              {{ delta(card.change) }}
            </p>
          </div>
          <p class="col-span-4 mt-4 text-xs text-muted-foreground">
            上游全池 {{ row.upstreamTotal }} 只 · 排除 ST {{ row.excludedStCount }} / 未开板新股 {{ row.excludedNewCount }}（合并去重 {{ row.excludedUnionCount }}）
          </p>
        </div>
      </section>
      <div class="grid grid-cols-3 gap-4 rounded-xl border p-4 text-sm">
        <div>
          早封率 <strong>{{ pct(row.earlyLimitUpRatio) }}</strong><p class="mt-1 text-xs text-muted-foreground">
            ≤{{ row.earlyTimeThreshold }}：{{ row.earlyLimitUpCount ?? '—' }} / 时间有效 {{ row.validLimitUpTimeCount ?? '—' }} · 覆盖 {{ pct(row.timeCoverage) }}
          </p><p class="text-xs text-muted-foreground">
            {{ delta(row.changes.earlyLimitUpRatio, true) }}；上游仅称“涨停时间”
          </p>
        </div>
        <div>
          封单留存中位数 <strong>{{ pct(row.sealRetentionMedian) }}</strong><p class="mt-1 text-xs text-muted-foreground">
            有效 {{ row.validSealRetentionCount ?? '—' }} 只 · 覆盖 {{ pct(row.sealRetentionCoverage) }}
          </p><p class="text-xs text-muted-foreground">
            {{ delta(row.changes.sealRetentionMedian, true) }}；封单结构代理，不保证不开板
          </p>
        </div>
        <div>
          当前封单额有效样本合计 <strong>{{ money(row.sealMoneySum) }}</strong><p class="mt-1 text-xs text-muted-foreground">
            有效 {{ row.validSealMoneyCount ?? '—' }} 只 · 金额覆盖 {{ pct(row.sealMoneyCoverage) }}；字段不全时并非全市场总额
          </p>
        </div>
      </div>
    </template>
    <SentimentCharts
      :history="history"
      :observation="row"
      @date="selectDate"
      @reason="filterReason"
    />
    <section class="space-y-4 rounded-xl border p-4">
      <div class="flex gap-2">
        <Button
          :variant="view === 'full' ? 'default' : 'outline'"
          @click="view = 'full'"
        >
          完整池梯队与晋级
        </Button><Button
          :variant="view === 'official' ? 'default' : 'outline'"
          @click="view = 'official'"
        >
          官方30日天梯 · 有限样本
        </Button>
      </div>
      <template v-if="view === 'full'">
        <div class="flex gap-2">
          <Button
            v-for="b in boards"
            :key="b"
            variant="outline"
            @click="filterBoard(b)"
          >
            {{ b }}板 · {{ row?.boardDistribution[b] ?? '—' }}只
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          真实完整池人数；最高板不截断。晋级逐代码匹配真实相邻交易日；未晋级仅表示未满足续板条件，不等于跌停或亏损。
        </p>
        <div class="grid grid-cols-4 gap-4">
          <details
            v-for="(p, key) in row?.promotions"
            :key="key"
            class="rounded-lg border p-3"
          >
            <summary class="cursor-pointer text-sm">
              {{ promotionLabels[key] ?? key }}：{{ pct(p.ratio) }}（{{ p.numerator ?? '—' }}/{{ p.denominator ?? '—' }}）
            </summary>
            <p class="my-2 text-xs text-muted-foreground">
              {{ p.sourceDate }} → {{ p.targetDate }} · {{ p.complete ? '完整口径' : '数据不足' }}
            </p>
            <p class="text-xs leading-6">
              晋级：{{ p.promotedCodes.join('、') || '—' }}
            </p><p class="text-xs leading-6">
              未晋级：{{ p.notPromotedCodes.join('、') || '—' }}
            </p>
          </details>
        </div>
      </template>
      <template v-else>
        <p class="text-sm text-muted-foreground">
          官方有限样本，每板位最多4只；不用于全市场计数或晋级率。实际窗口：{{ officialDates[0] ?? '—' }} ～ {{ officialDates.at(-1) ?? '—' }}（{{ ladder?.source?.window.length ?? '—' }}日）。窗口归属 {{ ladder?.source?.tradeDate ?? '—' }}。
        </p>
        <div
          v-if="ladder?.source"
          class="max-h-[500px] overflow-auto"
        >
          <table class="w-full text-left text-xs">
            <thead>
              <tr>
                <th class="p-2">
                  日期
                </th><th
                  v-for="(label, key) in officialBoards"
                  :key="key"
                  class="p-2"
                >
                  {{ label }}
                </th>
              </tr>
            </thead><tbody>
              <tr
                v-for="d in ladder.source.items"
                :key="d.date"
                class="border-t"
              >
                <td class="p-2">
                  {{ d.date }}
                </td><td
                  v-for="(_, key) in officialBoards"
                  :key="key"
                  class="p-2"
                >
                  <p
                    v-for="s in d.boards[key]"
                    :key="s.thscode"
                  >
                    {{ s.name }} {{ s.thscode }}（{{ s.boardNum }}板）
                  </p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p
          v-else
          class="py-8 text-center text-muted-foreground"
        >
          未获取截至所选日期的官方天梯
        </p>
      </template>
    </section>
    <section class="space-y-3">
      <h2 class="text-lg font-semibold">
        股票池明细 / 补充观察
      </h2>
      <div class="flex flex-wrap items-center gap-2">
        <Button
          v-for="(label, value) in poolLabels"
          :key="value"
          :variant="kind === value ? 'default' : 'outline'"
          @click="filterKind(value)"
        >
          {{ label }}
        </Button>
        <label
          v-if="kind === 'limit_up'"
          class="ml-2 flex items-center gap-2 text-sm"
        ><input
          v-model="scope"
          type="checkbox"
          true-value="all"
          false-value="main"
          @change="page = 1; loadPool()"
        >查看全部上游记录</label>
        <Input
          v-model="q"
          class="w-48"
          placeholder="代码或名称"
          aria-label="搜索股票"
          @keyup.enter="page = 1; loadPool()"
        /><Button
          variant="outline"
          @click="page = 1; loadPool()"
        >
          搜索
        </Button>
        <Button
          v-if="board || reason"
          variant="outline"
          @click="board = ''; reason = ''; page = 1; loadPool()"
        >
          清除 {{ board ? `${board}板` : '' }} {{ reason }}
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ kind === 'limit_up' ? '默认仅主观察口径；“查看全部”及其他筛选只改变本表，不改变顶部与历史统计。' : '独立上游全池口径；不参与情绪评分，不推导炸板率或封板成功率。' }} 当前筛选 {{ pool?.total ?? '—' }} / 上游全池 {{ pool?.upstreamTotal ?? '—' }}。
      </p>
      <AppApiErrorAlert
        v-if="poolError"
        :error="poolError"
        action-label="重试明细"
        @action="loadPool"
        @dismiss="poolError = null"
      />
      <Skeleton
        v-if="poolLoading"
        class="h-48"
      /><PoolTable
        v-else
        :pool="pool"
      />
      <div class="flex items-center justify-end gap-3 text-sm">
        <Button
          variant="outline"
          :disabled="page <= 1 || poolLoading"
          @click="page--; loadPool()"
        >
          上一页
        </Button>{{ page }}<Button
          variant="outline"
          :disabled="page * 50 >= (pool?.total ?? 0) || poolLoading"
          @click="page++; loadPool()"
        >
          下一页
        </Button>
      </div>
    </section>
    <section class="rounded-xl border p-4">
      <h2 class="mb-3 text-lg font-semibold">
        同日行业强度 Top5 · 独立旁证
      </h2>
      <div
        v-if="overview?.industryTop.length"
        class="flex flex-wrap gap-5 text-sm"
      >
        <span
          v-for="r in overview.industryTop"
          :key="r.industryCode"
        >{{ r.industryName }} · {{ r.strengthScore.toFixed(1) }}</span>
      </div>
      <p
        v-else
        class="text-sm text-muted-foreground"
      >
        所选日暂无行业强度快照
      </p>
      <p class="mt-3 text-xs text-muted-foreground">
        只读同日既有快照；涨停原因不自动对应行业，不触发行业计算。
      </p>
    </section>
  </div>
</template>
