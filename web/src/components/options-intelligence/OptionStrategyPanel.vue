<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { BookOpen, ChartNoAxesCombined, SlidersHorizontal, ShoppingBag, ArrowLeftRight, Wallet } from 'lucide-vue-next';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { dailyPatternMarketDate } from '@/utils/dailyPatterns';
import { formatPercent } from '@/utils/number';
import { OPTION_STRATEGIES, RISK_LABELS, strategyHint } from '@/utils/optionsStrategies/catalog';
import { STRATEGY_GROUPS, STRATEGY_REQUIREMENTS, strategyGroup, type StrategyGroup } from '@/utils/optionsStrategies/requirements';
import { HORIZONS, observeTrend, scoreStrategies, type StrategyHorizon } from '@/utils/optionsStrategies/scoring';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import MetricHint from '@/components/app/MetricHint.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

const props = defineProps<{ symbol: string; market: string; endDate?: string }>();
const horizon = ref<StrategyHorizon>('swing');
const group = ref<StrategyGroup>('buyer');
const groupIcons = { buyer: ShoppingBag, seller: ArrowLeftRight, capital: Wallet };
const groups = STRATEGY_GROUPS.map(settings => ({ ...settings,
  count: OPTION_STRATEGIES.filter(row => strategyGroup(row.setup) === settings.id).length }));
const data = shallowRef<DailyBarsResponse | null>(null);
const loading = ref(false), query = ref(''), category = ref(''), order = ref('desc'), page = ref(1);
const error = shallowRef<ParsedApiError | null>(null);
const evaluatedAt = ref(new Date());
const PAGE_SIZE = 8;
const observation = computed(() => observeTrend(data.value?.items ?? [], props.market, horizon.value, props.endDate, evaluatedAt.value));
const ranked = computed(() => scoreStrategies(observation.value).filter(row => strategyGroup(row.setup) === group.value)
  .map((row, index) => ({ ...row, rank: index + 1 })));
const categories = computed(() => [{ value: '', label: '全部结构' },
  ...[...new Set(ranked.value.map(s => s.category))].map(value => ({ value, label: value }))]);
const filtered = computed(() => ranked.value.filter(row => (!category.value || row.category === category.value)
  && `${row.name} ${row.english}`.toLowerCase().includes(query.value.trim().toLowerCase())).sort((a, b) => {
    if (a.score === null) return b.score === null ? a.id.localeCompare(b.id) : 1;
    if (b.score === null) return -1;
    return (order.value === 'desc' ? b.score - a.score : a.score - b.score) || a.id.localeCompare(b.id);
  }));
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
const visible = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE));
watch([query, category, order, horizon], () => { page.value = 1; });
watch(group, () => { query.value = ''; category.value = ''; page.value = 1; });
watch(pages, count => { page.value = Math.min(page.value, count); });
let generation = 0;
let controller: AbortController | undefined;
async function load() {
  const token = ++generation;
  controller?.abort(); controller = new AbortController();
  data.value = null; error.value = null; loading.value = true; page.value = 1;
  evaluatedAt.value = new Date();
  const today = dailyPatternMarketDate(props.market, evaluatedAt.value);
  const end = props.endDate && today && props.endDate < today ? props.endDate : today;
  if (!end) { loading.value = false; return; }
  const start = new Date(`${end}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 120);
  try {
    const result = await marketDataApi.dailyBars(props.symbol, end, start.toISOString().slice(0, 10), controller.signal);
    if (token !== generation) return;
    if (result.symbol !== props.symbol || result.market !== props.market) throw new Error('日K证券或市场与当前详情不一致，请重试。');
    data.value = result;
  } catch (cause) {
    if (token !== generation) return;
    const parsed = getParsedApiError(cause);
    if (parsed.status !== 404) error.value = parsed;
  } finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => props.endDate], load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
const scoringHelp = '固定规则，不调用LLM。短线使用最近5个交易日、波段使用最近10个交易日，分别需要6/11根日K。方向匹配占60分，趋势延续性占25分，收盘在观察区间中的位置占15分。方向由区间涨跌与对数价格回归斜率按日内真实波幅尺度归一化；延续性为净位移/逐日绝对位移。上涨型偏好上行，横盘型偏好低方向性与整理，保护型按对应持仓的对冲需要解读。仅描述已观察到的趋势，不推断未来IV或获利概率。套利类缺少同步报价与融资条件时不评分。';
</script>

<template>
  <section
    class="min-w-0 space-y-4 rounded-xl border bg-card p-4 sm:p-5"
    data-testid="option-strategy-panel"
  >
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex items-start gap-2.5">
        <ChartNoAxesCombined
          class="mt-0.5 size-4 shrink-0 text-muted-foreground"
          aria-hidden="true"
        /><div>
          <h3 class="flex items-center gap-1 text-sm font-semibold">
            <BilingualLabel
              zh="期权玩法适配"
              en="Strategy fit"
            /><MetricHint
              label="玩法适配评分"
              :description="scoringHelp"
            />
          </h3><p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            按当前K线趋势比较 {{ OPTION_STRATEGIES.length }} 种标准结构与常见扩展。
          </p>
        </div>
      </div>
      <div
        class="flex rounded-lg border bg-muted/25 p-1"
        aria-label="玩法观察周期"
      >
        <Button
          v-for="(settings, key) in HORIZONS"
          :key="key"
          size="sm"
          :variant="horizon === key ? 'secondary' : 'ghost'"
          :aria-pressed="horizon === key"
          :data-testid="`option-horizon-${key}`"
          @click="horizon = key"
        >
          {{ settings.label }} · {{ settings.sessions }} 日
        </Button>
      </div>
    </header>
    <p class="rounded-lg border border-dashed px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
      趋势适配分，不是获利概率。期权定价、持仓前提与可交易性需另行核验。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试日K"
      @action="load"
    />
    <div
      v-if="loading"
      role="status"
      aria-label="正在读取玩法评分日K"
      class="grid grid-cols-3 gap-2"
    >
      <Skeleton
        v-for="i in 3"
        :key="i"
        class="h-20"
      />
    </div>
    <template v-else>
      <dl class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div class="rounded-lg bg-muted/30 p-3">
          <dt class="text-[11px] text-muted-foreground">
            观察到的趋势
          </dt><dd class="mt-1 text-sm font-semibold">
            {{ observation.label }}
          </dd>
        </div>
        <div class="rounded-lg bg-muted/30 p-3">
          <dt class="text-[11px] text-muted-foreground">
            近 {{ observation.sessions }} 日涨跌
          </dt><dd class="mt-1 text-sm font-semibold tabular-nums">
            {{ formatPercent(observation.returnPct, { digits: 2, signed: true }) }}
          </dd>
        </div>
        <div class="rounded-lg bg-muted/30 p-3">
          <dt class="text-[11px] text-muted-foreground">
            趋势延续性
          </dt><dd class="mt-1 text-sm font-semibold tabular-nums">
            {{ observation.efficiency == null ? '—' : (observation.efficiency * 100).toFixed(0) }}<span class="ml-1 text-xs font-normal text-muted-foreground">/100</span>
          </dd>
        </div>
        <div class="rounded-lg bg-muted/30 p-3">
          <dt class="text-[11px] text-muted-foreground">
            日K截至
          </dt><dd class="mt-1 text-sm font-semibold tabular-nums">
            {{ observation.asOf ?? '—' }}
          </dd><dd
            v-if="observation.preview"
            class="mt-1 text-[11px] text-amber-600 dark:text-amber-400"
          >
            含当日未确认收盘日K · 预览
          </dd>
        </div>
      </dl>
      <p
        v-if="observation.status === 'unavailable'"
        class="rounded-lg bg-muted/25 p-3 text-xs text-muted-foreground"
        data-testid="option-strategy-unavailable"
      >
        {{ observation.reason }}玩法目录和说明仍可查看。
      </p>
    </template>
    <div
      class="grid gap-2 border-t pt-4 sm:grid-cols-3"
      role="group"
      aria-label="策略交易前提分组"
    >
      <button
        v-for="settings in groups"
        :key="settings.id"
        type="button"
        class="min-w-0 rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :class="group === settings.id ? 'border-foreground/35 bg-muted/50 shadow-sm' : 'border-border hover:bg-muted/25'"
        :aria-pressed="group === settings.id"
        :data-testid="`option-group-${settings.id}`"
        @click="group = settings.id"
      >
        <span class="flex items-center gap-2 text-sm font-semibold">
          <component
            :is="groupIcons[settings.id]"
            class="size-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <span class="min-w-0">{{ settings.label }}</span>
          <span class="ml-auto rounded-md bg-background px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground">{{ settings.count }}</span>
        </span>
        <span class="mt-1 block text-[10px] text-muted-foreground">{{ settings.english }}</span>
        <span class="mt-2 block text-[11px] leading-relaxed text-muted-foreground">{{ settings.description }}</span>
      </button>
    </div>
    <p class="text-[11px] leading-relaxed text-muted-foreground">
      持股、融券及预留本金的策略优先归入资金占用组。纯买方也可能权利金昂贵，实际成本取决于合约与数量。
    </p>
    <div class="grid grid-cols-2 items-center gap-2 sm:flex sm:flex-wrap">
      <SlidersHorizontal
        class="hidden size-4 text-muted-foreground sm:block"
        aria-hidden="true"
      /><Input
        v-model="query"
        aria-label="搜索期权玩法"
        placeholder="搜索玩法 / 英文名称"
        class="col-span-2 h-9 w-full sm:w-52"
      /><FieldSelect
        v-model="category"
        :options="categories"
        aria-label="玩法分类"
        class="min-w-0 sm:w-40"
        trigger-class="h-9"
      /><FieldSelect
        v-model="order"
        :options="[{ value: 'desc', label: '评分从高到低' }, { value: 'asc', label: '评分从低到高' }]"
        aria-label="玩法排序"
        class="min-w-0 sm:w-40"
        trigger-class="h-9"
      /><span class="text-xs text-muted-foreground">本组 {{ filtered.length }} / {{ ranked.length }} 种</span>
    </div>
    <div
      class="grid gap-3 sm:grid-cols-2"
      data-testid="option-strategy-list"
    >
      <article
        v-for="row in visible"
        :key="row.id"
        class="flex min-w-0 flex-col rounded-xl border p-4"
        :data-testid="`option-strategy-${row.id}`"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-start gap-1">
              <span
                class="mt-1 mr-1 text-[10px] tabular-nums text-muted-foreground"
                :aria-label="row.score == null ? '本组暂无排名' : `本组第${row.rank}名`"
              >{{ row.score == null ? '—' : `#${row.rank}` }}</span><h4 class="min-w-0 text-sm font-semibold">
                {{ row.name }}
              </h4><MetricHint
                :label="row.name"
                :description="strategyHint(row)"
              />
            </div><p class="mt-0.5 break-words text-[11px] text-muted-foreground">
              {{ row.english }}
            </p>
          </div>
          <div class="shrink-0 text-right">
            <p
              class="text-2xl font-semibold tracking-tight tabular-nums"
              :data-score="row.score"
              :class="row.score == null ? 'text-muted-foreground' : ''"
            >
              {{ loading ? '—' : row.score ?? '—' }}
            </p><p class="mt-0.5 text-[10px] text-muted-foreground">
              {{ row.score == null ? '暂不评分' : '趋势适配 /100' }}
            </p>
          </div>
        </div>
        <div class="my-3 flex flex-wrap gap-1.5">
          <Badge variant="secondary">
            {{ row.category }}
          </Badge><Badge :variant="row.risk === 'unlimited' ? 'warning' : 'outline'">
            {{ RISK_LABELS[row.risk] }}
          </Badge>
          <Badge
            v-for="label in STRATEGY_REQUIREMENTS[row.setup].labels"
            :key="label"
            variant="outline"
          >
            {{ label }}
          </Badge>
        </div>
        <div
          v-if="row.score != null && !loading"
          class="mb-3 h-1 overflow-hidden rounded-full bg-muted"
          aria-hidden="true"
        >
          <div
            class="h-full rounded-full bg-foreground/55"
            :style="{ width: `${row.score}%` }"
          />
        </div>
        <ul class="flex-1 space-y-1.5 text-xs leading-relaxed text-muted-foreground">
          <li
            v-for="reason in loading ? ['正在读取日K，暂不评分。'] : row.score == null ? row.reasons : row.reasons.slice(1)"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
        <details
          v-if="row.breakdown && !loading"
          class="mt-3 border-t pt-2 text-[11px] text-muted-foreground"
        >
          <summary class="cursor-pointer">
            评分拆解与使用前提
          </summary><p class="mt-2 tabular-nums">
            方向 {{ row.breakdown.direction.toFixed(1) }}/60 · 延续性 {{ row.breakdown.continuity.toFixed(1) }}/25 · 位置 {{ row.breakdown.location.toFixed(1) }}/15
          </p><p class="mt-2 leading-relaxed">
            {{ row.considerations }}
          </p><a
            :href="row.source"
            target="_blank"
            rel="noopener noreferrer"
            class="mt-2 inline-block underline"
          >结构参考 · OIC</a>
        </details>
      </article>
    </div>
    <p
      v-if="!visible.length"
      class="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"
    >
      没有匹配的玩法，请调整搜索或分类。
    </p>
    <AppPagination
      :current-page="page"
      :total-pages="pages"
      @page-change="page = $event"
    />
    <footer class="flex items-start gap-2 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
      <BookOpen
        class="mt-0.5 size-3.5 shrink-0"
        aria-hidden="true"
      /><p>
        同一结构的常见别名合并展示；0DTE等到期选择不作为独立玩法。<a
          href="https://www.optionseducation.org/strategies/all-strategies-en"
          target="_blank"
          rel="noopener noreferrer"
          class="underline"
        >OIC标准策略参考</a> · 本页规则未做收益回测，不调用LLM。
      </p>
    </footer>
  </section>
</template>
