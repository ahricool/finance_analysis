<script setup lang="ts">
import { useMarket } from '@/composables/useMarket';
import { formatRank } from '@/utils/rank';
import StockLink from '@/components/stocks/StockLink.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { confluenceApi as api, type ConfluenceRanking, type ConfluenceItem } from '@/api/confluence';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import { RefreshCcw } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { primary, secondary, labels, weights, signal, strength, agreement, tone } from '@/components/confluence/evidence';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const { market } = useMarket(); const tradeDate = ref(''); const dates = ref<string[]>([]);
const minSignals = ref<number>(); const minScore = ref(0); const industry = ref(''); const lifecycle = ref('');
const earlyOnly = ref(false); const topIndustry = ref(false); const strongOnly = ref(false);
const result = shallowRef<ConfluenceRanking | null>(null); const selected = shallowRef<ConfluenceItem | null>(null);
const error = shallowRef<ParsedApiError | null>(null); const loading = ref(false); const submitting = ref(false);
const taskId = ref(''); const dialogOpen = ref(false);
const page = ref(1);
const pageSize = 10;
const rankedItems = computed(() => result.value?.items.slice(0, 50) ?? []);
const pageCount = computed(() => Math.max(1, Math.ceil(rankedItems.value.length / pageSize)));
const pageItems = computed(() => rankedItems.value.slice((page.value - 1) * pageSize, page.value * pageSize));
const minimumScore = computed(() => result.value?.rules.minimumScore ?? 60);
const sectorMacro = computed(() => Boolean(result.value?.rules.macroMethod || result.value?.items.some(row => row.signals.macro?.evidence.macroMethod)));
let generation = 0; let runGeneration = 0;
async function load(reset = false) {
  const token = ++generation; loading.value = true; error.value = null; result.value = null;
  selected.value = null; dialogOpen.value = false; page.value = 1;
  if (reset) { tradeDate.value = ''; dates.value = []; minSignals.value = undefined; }
  try {
    const [ranking, availableDates] = await Promise.all([
      api.ranking({ market: market.value, trade_date: tradeDate.value || undefined, min_score: Number(minScore.value),
        min_signals: minSignals.value === undefined ? undefined : Number(minSignals.value), industry: industry.value || undefined, lifecycle: lifecycle.value || undefined,
        early_only: earlyOnly.value, top_industry: topIndustry.value, strong_only: strongOnly.value, limit: 50 }),
      api.dates(market.value),
    ]);
    if (token !== generation) return;
    result.value = ranking; dates.value = availableDates;
    if (minSignals.value === undefined) minSignals.value = ranking.rules.minSignals;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch(market, () => {
  ++runGeneration; submitting.value = false; taskId.value = '';
  void load(true);
});
function selectDate(value: string) {
  tradeDate.value = value;
  minSignals.value = undefined;
  void load();
}
function show(row: ConfluenceItem) { selected.value = row; dialogOpen.value = true; }
async function run() {
  const token = ++runGeneration;
  submitting.value = true; error.value = null; taskId.value = '';
  try {
    const result = await api.run(market.value, tradeDate.value || undefined);
    if (token === runGeneration) taskId.value = result.taskId;
  }
  catch (cause) { if (token === runGeneration) error.value = getParsedApiError(cause); }
  finally { if (token === runGeneration) submitting.value = false; }
}
function configuredWeight(key: keyof typeof weights) {
  return result.value?.rules.weights?.[key] ?? result.value?.items[0]?.signals[key]?.weight ?? (result.value?.algorithmVersion?.startsWith('confluence_v2') ? weights[key] : null);
}
function configuredLabel(key: keyof typeof weights) { return key === 'macro' && !sectorMacro.value ? '宏观环境' : labels[key]; }
function frameworkTotal(keys: Array<keyof typeof weights>) { return keys.reduce((sum, key) => sum + (configuredWeight(key) ?? 0), 0); }
onMounted(() => { void load(); });
onBeforeUnmount(() => { ++generation; ++runGeneration; });
const detailInitialTab = ref<'overview' | 'confluence'>('confluence');
</script>

<template>
  <div
    class="min-w-0 space-y-6"
    data-testid="confluence-page"
  >
    <PageHeader
      variant="section"
      title="多信号共振"
      en="SIGNAL CONFLUENCE"
      description="展示前50条研究排行，每页10条；每个市场每日精选最多10个，其余仅供观察。"
    >
      <template #actions>
        <Button
          variant="outline"
          :disabled="loading"
          aria-label="刷新共振"
          @click="load()"
        >
          <RefreshCcw class="mr-2 size-4" />刷新
        </Button>
        <Button
          v-if="currentUser?.role === 'admin'"
          :disabled="submitting"
          @click="run"
        >
          {{ submitting ? '提交中…' : '生成信号' }}
        </Button>
      </template>
    </PageHeader>
    <div class="flex flex-wrap items-center gap-3 rounded-xl border bg-card px-4 py-3">
      <label
        for="confluence-date-picker"
        class="text-xs font-medium text-muted-foreground"
      >快照日期</label>
      <AppDatePicker
        id="confluence-date-picker"
        :model-value="tradeDate || result?.tradeDate || ''"
        :available-dates="dates"
        disable-weekends
        data-testid="confluence-date"
        @update:model-value="selectDate"
      />
      <span class="ml-auto text-xs text-muted-foreground">{{ result?.generatedAt ? `更新于 ${formatDateTime(result.generatedAt)}` : '等待正式结果' }}</span>
      <Badge
        v-if="result?.algorithmVersion"
        variant="outline"
      >
        {{ result.algorithmVersion }}
      </Badge>
    </div>
    <p
      v-if="taskId"
      class="text-sm text-muted-foreground"
      role="status"
    >
      任务已提交：{{ taskId }}，完成后刷新查看。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load()"
    />
    <div
      v-if="loading"
      class="rounded-xl border p-10 text-center text-sm text-muted-foreground"
      role="status"
    >
      正在读取正式共振快照…
    </div>
    <template v-else-if="result">
      <section
        class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        aria-label="当日研究概况"
      >
        <div class="rounded-xl border border-foreground/15 bg-gradient-to-br from-muted/60 to-card p-5">
          <p class="text-xs text-muted-foreground">
            当日精选
          </p><p
            class="mt-2 text-3xl font-semibold tabular-nums"
            data-testid="selected-count"
          >
            {{ result.summary.eligible }}<span class="ml-2 text-sm font-normal text-muted-foreground">{{ result.rules.maxSignals ? `/ ${result.rules.maxSignals}` : '历史快照' }}</span>
          </p><p class="mt-2 text-xs text-muted-foreground">
            按证据一致性排序 · 不凑名额
          </p>
        </div>
        <div class="rounded-xl border bg-card p-5">
          <p class="text-xs text-muted-foreground">
            高共振
          </p><p class="mt-2 text-3xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
            {{ result.summary.strongConfluence }}
          </p><p class="mt-2 text-xs text-muted-foreground">
            {{ result.algorithmVersion?.startsWith('confluence_v2') ? `分数 ≥ ${result.rules.strongMinScore} · 主要证据一致偏强` : '按历史保存的强共振规则' }}
          </p>
        </div>
        <div class="rounded-xl border bg-card p-5">
          <p class="text-xs text-muted-foreground">
            合格候选
          </p><p class="mt-2 text-3xl font-semibold tabular-nums">
            {{ result.summary.candidateCount ?? result.summary.eligible }}
          </p><p class="mt-2 text-xs text-muted-foreground">
            满足精选门槛与主要证据要求，最多入选10个
          </p>
        </div>
        <div class="rounded-xl border bg-card p-5">
          <p class="text-xs text-muted-foreground">
            宏观背景 · 全市场
          </p><p class="mt-2 text-2xl font-semibold">
            <BilingualEnum
              :value="String(result.sourceAvailability.macro?.evidence?.regime ?? result.items[0]?.signals.macro?.evidence.regime ?? '—')"
              size="large"
            />
          </p><p class="mt-2 text-xs text-muted-foreground">
            {{ result.sourceAvailability.macro?.tradeDate ?? result.items[0]?.signals.macro?.tradeDate ?? '无可用指标，权重自动分摊' }}
            <span
              v-if="sectorMacro"
              class="mt-1 block"
            >个股使用所属行业宏观适配度评分</span>
          </p>
        </div>
      </section>
      <p
        v-if="!result.algorithmVersion?.startsWith('confluence_v2')"
        class="text-xs text-muted-foreground"
      >
        历史版本：保留原始评分与权重；新增指标留空。
      </p>
      <p
        v-if="result.algorithmVersion === 'confluence_v2'"
        class="text-xs text-muted-foreground"
      >
        该历史版本宏观维度使用统一风险偏好分，尚未应用行业适配。
      </p>
      <section
        class="overflow-hidden rounded-xl border bg-card"
        aria-label="评分框架"
      >
        <div class="grid lg:grid-cols-[1fr_1fr]">
          <div class="p-4 lg:border-r">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold">
                主要指标
              </h2><span class="text-xs text-muted-foreground">基础权重 {{ frameworkTotal(primary) }}%</span>
            </div><div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div
                v-for="key in primary"
                :key="key"
                class="rounded-lg bg-muted/50 px-3 py-2"
              >
                <p class="text-xs">
                  {{ configuredLabel(key) }}
                </p><p class="mt-1 text-sm font-medium tabular-nums">
                  {{ configuredWeight(key) ?? '—' }}<span class="text-xs text-muted-foreground">%</span>
                </p>
              </div>
            </div>
          </div>
          <div class="p-4">
            <div class="mb-3 flex items-center justify-between">
              <h2 class="text-sm font-semibold">
                辅助指标
              </h2><span class="text-xs text-muted-foreground">基础权重 {{ frameworkTotal(secondary) }}%</span>
            </div><div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div
                v-for="key in secondary"
                :key="key"
                class="rounded-lg bg-muted/30 px-3 py-2"
              >
                <p class="text-xs text-muted-foreground">
                  {{ configuredLabel(key) }}
                </p><p class="mt-1 text-sm font-medium tabular-nums">
                  {{ configuredWeight(key) ?? '—' }}<span class="text-xs text-muted-foreground">%</span>
                </p>
              </div>
            </div>
          </div>
        </div>
        <p class="border-t bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground">
          缺失留空，可用指标按基础权重比例重新归一。趋势包含 20 / 40 / 60 日的趋势、突破与超跌反弹；同周期替代形态不叠加。
        </p>
      </section>
      <section class="space-y-3">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold">
              研究排行与精选
            </h2><p class="mt-1 text-xs text-muted-foreground">
              点击股票查看行情，点击行查看完整共振证据。
            </p>
          </div><div class="flex flex-wrap items-center gap-2">
            <label class="grid gap-1 text-xs text-muted-foreground"><span>最低共振分</span>            <Input
              v-model.number="minScore"
              type="number"
              min="0"
              max="100"
              class="w-28"
              aria-label="最低分数"
              placeholder="最低分"
            />
            </label><label class="grid gap-1 text-xs text-muted-foreground"><span>有效维度</span>            <Input
              v-model.number="minSignals"
              type="number"
              min="1"
              max="8"
              class="w-28"
              aria-label="最低有效维度"
              placeholder="有效维度"
            />
            </label>            <Button
              variant="outline"
              @click="load()"
            >
              筛选
            </Button>
          </div>
        </div>
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <p class="font-medium text-foreground">
            前50条研究排行（百分比相对当前筛选结果）
          </p>
          <p>精选优先，其余按综合分排列 · 精选门槛 {{ minimumScore }} 分 · 观察项不属于正式信号</p>
        </div>
        <div class="overflow-x-auto rounded-xl border bg-card">
          <Table class="min-w-[1080px]">
            <TableHeader>
              <TableRow class="bg-muted/35 hover:bg-muted/35">
                <TableHead class="w-44">
                  证券 / 证据一致性
                </TableHead><TableHead class="w-28">
                  共振分
                </TableHead><TableHead
                  v-for="key in primary"
                  :key="key"
                  class="w-24"
                >
                  {{ configuredLabel(key) }}
                </TableHead><TableHead class="w-60">
                  辅助证据
                </TableHead><TableHead class="w-24 text-right">
                  有效权重
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="(row, index) in pageItems"
                :key="row.code"
                class="cursor-pointer"
                tabindex="0"
                @click="detailInitialTab = 'confluence'; show(row)"
                @keydown.enter.self="detailInitialTab = 'confluence'; show(row)"
                @keydown.space.self.prevent="detailInitialTab = 'confluence'; show(row)"
              >
                <TableCell class="py-5">
                  <div class="flex items-start gap-3">
                    <span class="mt-1 font-mono text-xs text-muted-foreground">{{ formatRank((page - 1) * pageSize + index + 1, result?.total) }}</span><div>
                      <StockLink
                        :code="row.code"
                        :name="row.name"
                        :market="market"
                        @select="detailInitialTab = 'overview'; show(row)"
                      /><p class="mt-2 text-xs text-muted-foreground">
                        主要证据正向 {{ agreement(row) }}
                      </p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <p class="text-2xl font-semibold tabular-nums tracking-tight">
                    {{ row.confluenceScore?.toFixed(2) ?? '—' }}
                  </p>
                  <Badge
                    v-if="row.eligible"
                    variant="secondary"
                    class="mt-1"
                  >
                    精选
                  </Badge>
                  <Badge
                    v-else
                    variant="outline"
                    class="mt-1 text-muted-foreground"
                  >
                    观察项
                  </Badge>
                  <Badge
                    v-if="row.confluenceScore !== null && row.confluenceScore < minimumScore"
                    variant="outline"
                    class="mt-1 border-amber-500/40 text-amber-700 dark:text-amber-300"
                    data-testid="below-threshold"
                  >
                    低于{{ minimumScore }}分
                  </Badge>
                  <Badge
                    v-if="row.strongConfluence"
                    variant="secondary"
                    class="mt-1 text-emerald-700 dark:text-emerald-300"
                  >
                    高共振
                  </Badge>
                </TableCell>
                <TableCell
                  v-for="key in primary"
                  :key="key"
                >
                  <p
                    class="text-base font-semibold tabular-nums"
                    :class="tone(signal(row, key).status)"
                  >
                    {{ strength(row, key)?.toFixed(0) ?? '—' }}
                  </p><p class="mt-1 text-[10px] text-muted-foreground">
                    {{ signal(row, key).tradeDate ?? '无数据' }}
                  </p>
                </TableCell>
                <TableCell>
                  <div class="grid grid-cols-2 gap-x-4 gap-y-2">
                    <div
                      v-for="key in secondary"
                      :key="key"
                      class="flex items-center justify-between gap-2 text-xs"
                    >
                      <span class="text-muted-foreground">{{ configuredLabel(key) }}</span><span
                        class="font-medium tabular-nums"
                        :class="tone(signal(row, key).status)"
                      >{{ strength(row, key)?.toFixed(0) ?? '—' }}</span>
                    </div>
                  </div>
                </TableCell>
                <TableCell class="text-right">
                  <p class="font-medium tabular-nums">
                    {{ row.availableWeight }}<span class="text-xs text-muted-foreground">/100</span>
                  </p><p class="mt-1 text-xs text-muted-foreground">
                    {{ row.availableSignalCount }} 个维度
                  </p>
                </TableCell>
              </TableRow>
              <TableRow v-if="!result.items.length">
                <TableCell
                  :colspan="8"
                  class="py-14 text-center"
                >
                  <p class="font-medium">
                    {{ result.generatedAt ? '暂无符合条件的高一致性信号' : '暂无正式共振快照' }}
                  </p><p class="mt-2 text-xs text-muted-foreground">
                    缺少核心证据时留空；每日上限是 10 个，不是必须产出 10 个。
                  </p>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <nav
          v-if="rankedItems.length"
          aria-label="研究排行分页"
          data-testid="confluence-pagination"
          class="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground"
        >
          <p>第 {{ page }} / {{ pageCount }} 页 · 每页 {{ pageSize }} 条 · 当前 {{ rankedItems.length }} 条</p>
          <div class="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              :disabled="page === 1"
              @click="page--"
            >
              上一页
            </Button>
            <Button
              variant="outline"
              size="sm"
              :disabled="page >= pageCount"
              @click="page++"
            >
              下一页
            </Button>
          </div>
        </nav>
      </section>
      <details class="rounded-xl border bg-card px-4 py-3 text-xs">
        <summary class="cursor-pointer font-medium">
          数据来源与评分说明
        </summary><div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div
            v-for="key in [...primary, ...secondary]"
            :key="key"
          >
            <p class="font-medium">
              {{ configuredLabel(key) }}
            </p><p class="mt-1 text-muted-foreground">
              {{ result.sourceAvailability[key]?.status ?? 'unavailable' }} · {{ result.sourceAvailability[key]?.tradeDate ?? '—' }}
            </p><p class="mt-1 text-muted-foreground">
              {{ result.sourceAvailability[key]?.reason ?? '仅使用已保存的正式核心指标' }}
            </p>
          </div>
        </div><p class="mt-4 border-t pt-3 text-muted-foreground">
          分数表示规则下的证据支持度，不是上涨概率。来源失败和不适用均保持缺失；历史快照保留当时版本。
        </p>
      </details>
    </template>
    <StockDetailDialog
      v-model:open="dialogOpen"
      :stock="selected ? { code: selected.code, name: selected.name, marketType: market } : null"
      kind="research"
      :initial-tab="detailInitialTab"
      :context="{ tradeDate: result?.tradeDate || undefined, view: 'official' }"
    />
  </div>
</template>
