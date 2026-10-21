<script setup lang="ts">
import StockLink from '@/components/stocks/StockLink.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { confluenceApi as api, type ConfluenceRanking, type ConfluenceItem, type Market, type SignalKey } from '@/api/confluence';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import { RefreshCcw } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const market = ref<Market>('CN'); const tradeDate = ref(''); const dates = ref<string[]>([]);
const minSignals = ref<number>(); const minScore = ref(0); const industry = ref(''); const lifecycle = ref('');
const earlyOnly = ref(false); const topIndustry = ref(false); const strongOnly = ref(false);
const result = shallowRef<ConfluenceRanking | null>(null); const selected = shallowRef<ConfluenceItem | null>(null);
const error = shallowRef<ParsedApiError | null>(null); const loading = ref(false); const submitting = ref(false);
const taskId = ref(''); const dialogOpen = ref(false);
const keys: SignalKey[] = ['industry', 'trend', 'quant', 'etf', 'dragonTiger'];
const labels: Record<SignalKey, string> = { industry: '行业', trend: '趋势', quant: 'Quant', etf: 'ETF', dragonTiger: '龙虎榜资金' };
const states = { positive: '正向', neutral: '中性', negative: '负向', unavailable: '无数据' };
let generation = 0;
async function load(reset = false) {
  const token = ++generation; loading.value = true; error.value = null; result.value = null;
  selected.value = null; dialogOpen.value = false;
  if (reset) { tradeDate.value = ''; dates.value = []; minSignals.value = undefined; }
  try {
    const [ranking, availableDates] = await Promise.all([
      api.ranking({ market: market.value, trade_date: tradeDate.value || undefined, min_score: Number(minScore.value),
        min_signals: minSignals.value === undefined ? undefined : Number(minSignals.value), industry: industry.value || undefined, lifecycle: lifecycle.value || undefined,
        early_only: earlyOnly.value, top_industry: topIndustry.value, strong_only: strongOnly.value, limit: 200 }),
      api.dates(market.value),
    ]);
    if (token !== generation) return;
    result.value = ranking; dates.value = availableDates;
    if (minSignals.value === undefined) minSignals.value = ranking.rules.minSignals;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function setMarket(target: Market) {
  if (target === market.value) return;
  market.value = target;
  void load(true);
}
function selectDate(value: string) {
  tradeDate.value = value;
  minSignals.value = undefined;
  void load();
}
function show(row: ConfluenceItem) { selected.value = row; dialogOpen.value = true; }
async function run() {
  submitting.value = true; error.value = null; taskId.value = '';
  try { taskId.value = (await api.run(market.value, tradeDate.value || undefined)).taskId; }
  catch (cause) { error.value = getParsedApiError(cause); }
  finally { submitting.value = false; }
}
function evidence(row: ConfluenceItem, key: SignalKey, field: string) { return row.signals[key].evidence[field] ?? '—'; }
onMounted(() => { void load(); });
onBeforeUnmount(() => { ++generation; });
const detailInitialTab = ref<'overview' | 'confluence'>('confluence');
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="confluence-page"
  >
    <PageHeader
      variant="section"
      title="多信号共振"
      en="Signal Confluence"
      description="面向 2–14 天的正式结果交叉确认。先看证据与覆盖，再看分数。"
    >
      <template #actions>
        <ResearchMarketToggle
          :model-value="market"
          data-testid="confluence-market-switcher"
          @update:model-value="setMarket"
        />
        <AppDatePicker
          :model-value="tradeDate || result?.tradeDate || ''"
          label="快照日期"
          placeholder="最新快照"
          :available-dates="dates"
          :disabled="loading || !dates.length"
          disable-weekends
          class="w-56"
          data-testid="confluence-date"
          @update:model-value="selectDate"
        />
        <Button
          variant="outline"
          class="h-10"
          :disabled="loading"
          @click="load()"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <Button
          v-if="currentUser?.role === 'admin'"
          class="h-10"
          :disabled="submitting"
          @click="run"
        >
          生成快照
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="taskId"
      class="text-sm text-muted-foreground"
    >
      任务已提交：{{ taskId }}。完成后刷新查看。
    </p>
    <div class="flex flex-wrap items-end gap-3 rounded-lg border p-4">
      <label class="grid gap-1 text-sm">最低有效维度<Input
        v-model="minSignals"
        aria-label="最低有效维度"
        class="h-10 w-28"
        type="number"
        min="1"
        max="5"
      /></label>
      <label class="grid gap-1 text-sm">最低分数<Input
        v-model="minScore"
        aria-label="最低分数"
        class="h-10 w-24"
        type="number"
        min="0"
        max="100"
      /></label>
      <label class="grid gap-1 text-sm">行业<Input
        v-model="industry"
        aria-label="行业"
        class="h-10 w-32"
        placeholder="名称或代码"
      /></label>
      <label class="grid gap-1 text-sm"><IndicatorHelpLabel
        scope="confluence"
        label="lifecycle"
        compact
      /><select
        v-model="lifecycle"
        aria-label="生命周期"
        class="block h-10 rounded-md border bg-background px-3"
      ><option value="">全部</option><option
        v-for="phase in ['IGNITION', 'EMERGING', 'EXPANSION', 'MATURE', 'EXHAUSTION', 'BROKEN']"
        :key="phase"
        :value="phase"
      >{{ phase }}</option></select></label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="earlyOnly"
        type="checkbox"
      >仅点火 / 萌芽</label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="topIndustry"
        type="checkbox"
      >行业 Top10</label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="strongOnly"
        type="checkbox"
      >仅强共振</label>
      <Button
        :disabled="loading"
        @click="load()"
      >
        筛选
      </Button>
    </div>
    <p class="text-sm text-muted-foreground">
      正向贡献全权重，中性贡献一半，负向为 0；无数据不参与分母。至少 {{ result?.rules.minSignals ?? '—' }} 个有效维度进入默认榜单。V1 启发式规则，未经回测验证。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取正式快照…
    </p>
    <template v-if="result">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            <IndicatorHelpLabel
              scope="confluence"
              label="strongConfluence"
            />
          </p><p class="text-2xl font-semibold">
            {{ result.summary.strongConfluence }}
          </p><p class="text-xs text-muted-foreground">
            至少 {{ result.rules.strongMinSignals }} 维 / {{ result.rules.strongMinPositive }} 正向 / {{ result.rules.strongMinScore }} 分
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            <IndicatorHelpLabel
              scope="confluence"
              label="ignitionTopIndustry"
            />
          </p><p class="text-2xl font-semibold">
            {{ result.summary.ignitionIndustryStrong }}
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            <IndicatorHelpLabel
              scope="confluence"
              label="topIndustryConfluence"
            />
          </p><p class="text-2xl font-semibold">
            {{ result.summary.topIndustryConfluence }}
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            <IndicatorHelpLabel
              scope="confluence"
              label="snapshotTradeDate"
            />
          </p><p class="text-xl font-semibold">
            {{ result.tradeDate ?? '暂无快照' }}
          </p><p class="text-xs text-muted-foreground">
            生成 {{ result.generatedAt ? formatDateTime(result.generatedAt) : '—' }}
          </p>
        </div>
      </div>
      <div class="rounded-lg border p-4 text-sm space-y-2">
        <p class="font-medium">
          来源覆盖 · 各维度日期独立，可能早于目标日期
        </p>
        <p
          v-for="(source, key) in result.sourceAvailability"
          :key="key"
        >
          <span class="font-medium">{{ labels[key] }}</span> · {{ source.tradeDate ?? '无正式日期' }} · {{ source.count }} 条 · {{ source.status === 'available' ? '可用' : source.status === 'failed' ? '读取失败' : '不可用' }}<span v-if="source.reason"> · {{ source.reason }}</span>
        </p>
        <p
          v-if="market === 'US'"
          class="text-muted-foreground"
        >
          US 当前可能仅有趋势与 Quant 两个维度。可将最低维度设为 2 查看有限证据，不能因此认定为高共振。
        </p>
      </div>
      <p class="text-sm text-muted-foreground">
        匹配 {{ result.total }} 只，显示前 {{ result.items.length }} 只；摘要为整日统计。Signals = 正向 / 有效维度（共 5 维）。
      </p>
      <div class="rounded-lg border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="股票"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="confluence"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="signals"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="industry"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="lifecycleFragility"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="quantRank"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="etfRank"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="龙虎榜资金"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="confluence"
                  label="whyConfluence"
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
              @click="detailInitialTab = 'confluence'; show(row)"
              @keydown.enter.self="detailInitialTab = 'confluence'; show(row)"
              @keydown.space.self.prevent="detailInitialTab = 'confluence'; show(row)"
            >
              <TableCell>
                <StockLink
                  :code="row.code"
                  :name="row.name"
                  :market="market"
                  @select="detailInitialTab = 'overview'; show(row)"
                />
              </TableCell>
              <TableCell>
                <strong>{{ row.confluenceScore?.toFixed(1) ?? '—' }}</strong><p class="text-xs text-muted-foreground">
                  权重 {{ row.availableWeight }}/100
                </p><Badge
                  v-if="!row.eligible"
                  variant="outline"
                >
                  证据不足
                </Badge>
              </TableCell>
              <TableCell>{{ row.positiveSignalCount }}/{{ row.availableSignalCount }}</TableCell>
              <TableCell>
                {{ evidence(row, 'industry', 'industryName') }}<p class="text-xs">
                  Rank {{ evidence(row, 'industry', 'strengthRank') }}
                </p>
              </TableCell>
              <TableCell>
                {{ evidence(row, 'trend', 'trendLifecycle') }}<p class="text-xs">
                  脆弱性 {{ evidence(row, 'trend', 'fragilityScore') }}
                </p>
              </TableCell>
              <TableCell>{{ evidence(row, 'quant', 'universeRank') }}</TableCell><TableCell>{{ evidence(row, 'etf', 'rank') }}</TableCell>
              <TableCell>{{ row.signals.dragonTiger.status === 'unavailable' ? '无数据' : evidence(row, 'dragonTiger', 'netInflow') }}</TableCell>
              <TableCell class="max-w-80 whitespace-normal">
                <div class="flex flex-wrap gap-1 mb-2">
                  <Badge
                    v-for="key in keys"
                    :key="key"
                    variant="outline"
                    :class="{ 'text-market-up': row.signals[key].status === 'positive', 'text-market-down': row.signals[key].status === 'negative', 'text-muted-foreground': row.signals[key].status === 'unavailable' }"
                  >
                    {{ labels[key] }} {{ states[row.signals[key].status] }} {{ row.signals[key].score ?? '—' }}
                  </Badge>
                </div><p
                  v-for="key in keys.filter(k => row.signals[k].status !== 'unavailable')"
                  :key="key"
                  class="text-xs"
                >
                  {{ row.signals[key].reasons[0] }} · {{ row.signals[key].tradeDate }}
                </p>
              </TableCell>
            </TableRow>
            <TableRow v-if="!result.items.length">
              <TableCell
                :colspan="9"
                class="py-10 text-center text-muted-foreground"
              >
                {{ result.generatedAt ? '没有满足当前条件的股票；缺失信号不会被补为零分。' : '暂无正式共振快照，等待任务生成。' }}
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
      :context="{ tradeDate: result?.tradeDate || undefined, view: 'official' }"
    />
  </div>
</template>
