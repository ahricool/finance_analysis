<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue';
import { ChevronDown, ChevronRight, Download, ScanLine } from 'lucide-vue-next';
import apiClient from '@/api';
import { toast } from 'vue-sonner';
import { toCamelCase } from '@/api/utils';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import StockLink from '@/components/stocks/StockLink.vue';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { exportExcel } from '@/utils/excelExport';
import { formatFixed, formatPercent } from '@/utils/number';
import { filterOpportunities, opportunityColumns, opportunityStates, patternNames, opportunityValue,
  type OpportunitySort, type OpportunityItem, type OpportunityBranch, type OpportunityResponse } from './opportunities';
const DailyKLineCard = defineAsyncComponent(() => import('@/components/market-data/DailyKLineCard.vue'));
const props = defineProps<{ market: 'CN' | 'US'; tradeDate?: string; mode: 'official' | 'preview'; refreshKey?: number }>();
const data = ref<OpportunityResponse | null>(null);
const loading = ref(false), error = ref<ParsedApiError | null>(null);
const state = ref('CONFIRMED'), kind = ref(''), search = ref(''), page = ref(1);
const sort = ref<OpportunitySort | null>(null), direction = ref<'asc' | 'desc'>('desc');
const expanded = ref<string | null>(null), selected = ref<OpportunityBranch | null>(null);
let request: AbortController | undefined;
async function load() {
  request?.abort(); const current = new AbortController(); request = current;
  loading.value = true; error.value = null; data.value = null; expanded.value = null; selected.value = null;
  try {
    const response = await apiClient.get('/api/v1/trend-following/opportunities', {
      params: { market: props.market, trade_date: props.tradeDate || undefined, mode: props.mode }, signal: current.signal,
    });
    if (request === current) data.value = toCamelCase<OpportunityResponse>(response.data);
  } catch (err) { if (!current.signal.aborted && request === current) error.value = getParsedApiError(err); }
  finally { if (request === current) loading.value = false; }
}
watch(() => [props.market, props.tradeDate, props.mode, props.refreshKey], load, { immediate: true });
onBeforeUnmount(() => request?.abort());
watch([state, kind, search, sort, direction, data], () => { page.value = 1; });
const filtered = computed(() => filterOpportunities(data.value?.items ?? [], state.value, kind.value,
  search.value, sort.value, direction.value));
const visible = computed(() => filtered.value.slice((page.value - 1) * 10, page.value * 10));
const historyLabels: Record<string, string> = { complete: '完整', partial: '部分形态历史不足',
  insufficient: '历史不足，无法判断', invalid_ohlc: 'OHLC 异常，无法判断', missing_sessions: '缺交易日，无法判断' };
const stateOptions = [{ value: '', label: '全部状态' }, { value: 'FRESH', label: '今日首次确认' },
  ...Object.entries(opportunityStates).map(([value, label]) => ({ value, label }))];
const evidenceLabels: Record<string, string> = {
  depth: '平台深度', slope: '平台斜率', tightness: '收盘紧凑度', upperTouches: '上沿触及', lowerTouches: '下沿触及',
  terminalWidth: '末端宽度', volumeDryRatio: '整理量能比', cupDepth: '杯体深度', handleDepth: '柄深度',
  recovery: '右侧恢复比例', bottomSessions: '杯底附近天数', boxQuality: '箱体质量', boxWidthPct: '箱体宽度',
  boxUpperTouches: '上沿触及', boxLowerTouches: '下沿触及',
};
const evidenceMetrics = computed(() => Object.entries(selected.value?.evidence ?? {})
  .filter(([key, value]) => key in evidenceLabels && typeof value === 'number')
  .map(([key, value]) => ({ label: evidenceLabels[key], value: formatFixed(Number(value)) })));
const kindOptions = [{ value: '', label: '全部形态' }, ...Object.entries(patternNames).map(([value, label]) => ({ value, label }))];
function changeSort(key: OpportunitySort) {
  direction.value = sort.value === key && direction.value === 'desc' ? 'asc' : 'desc'; sort.value = key;
}
function toggle(item: OpportunityItem) {
  expanded.value = expanded.value === item.code ? null : item.code;
  selected.value = item.primary ?? item.display;
}
function otherLabels(item: OpportunityItem) {
  const primaryKind = (item.primary ?? item.display)?.kind;
  return [...new Set(item.branches.filter(b => b.kind !== primaryKind && b.status !== 'INVALIDATED')
    .map(b => patternNames[b.kind] ?? b.kind))].slice(0, 2).join(' · ');
}
function cell(item: OpportunityItem, key: OpportunitySort) {
  const value = opportunityValue(item, key);
  if (value == null) return key === 'status' ? historyLabels[item.historyStatus] ?? '无法判断' : '—';
  if (key === 'kind') return patternNames[String(value)] ?? value;
  if (key === 'status') return opportunityStates[String(value)] ?? value;
  if (key === 'distancePct') return formatPercent(Number(value));
  return typeof value === 'number' ? formatFixed(value) : value;
}
async function download() {
  try {
  await exportExcel(`买点机会-${props.market}-${data.value?.tradeDate}.xlsx`, '买点机会',
    [{ label: '代码' }, ...opportunityColumns.map(([key, label]) => ({ label, format: key === 'distancePct' ? '0.00%' : undefined })), { label: '规则版本' }, { label: '模式' }],
    filtered.value.map(item => [item.code, ...opportunityColumns.map(([key]) => key === 'kind' || key === 'status' ? cell(item, key) : opportunityValue(item, key)),
      (item.primary ?? item.display)?.ruleVersion, props.mode]));
  } catch { toast.error('买点机会导出失败，请重试'); }
}
</script>

<template>
  <Card
    class="overflow-hidden"
    data-testid="trend-opportunities"
  >
    <CardHeader class="border-b bg-muted/20 pb-5">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="space-y-2">
          <CardTitle class="flex items-center gap-2 text-base">
            <ScanLine class="size-4 text-muted-foreground" />买点机会
            <Badge
              variant="outline"
              class="font-normal"
            >
              OHLCV · V1
            </Badge>
          </CardTitle>
          <CardDescription>汇总 10 / 20 / 40 日趋势背景，同票合并展示，不受下方趋势周期切换影响。质量为规则匹配度，不代表胜率。</CardDescription>
        </div>
        <Button
          variant="outline"
          size="sm"
          :disabled="!filtered.length"
          @click="download"
        >
          <Download class="size-3.5" />导出筛选结果
        </Button>
      </div>
      <div
        v-if="data"
        class="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground tabular-nums"
      >
        <span>已识别 <strong class="font-medium text-foreground">{{ data.coveredCount }} / {{ data.scannedCount }}</strong></span>
        <span>有效买点 <strong class="font-medium text-foreground">{{ data.candidateCount }}</strong></span>
        <span>信号中心按分支质量取前 {{ data.candidateLimit }} 只 · 超出 {{ Math.max(0, data.candidateCount - data.candidateLimit) }} 只</span>
        <span v-if="data.generatedAt">生成于 {{ data.generatedAt.replace('T', ' ').slice(0, 19) }} UTC</span>
      </div>
    </CardHeader>
    <CardContent class="space-y-4 p-4 sm:p-5">
      <div
        v-if="mode === 'preview'"
        class="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground"
      >
        盘中预演：所有确认待收盘验证；累计量不参与严格日量确认，不产生正式事件。
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <FieldSelect
          v-model="state"
          :options="stateOptions"
          class="w-40"
          aria-label="买点状态"
        />
        <FieldSelect
          v-model="kind"
          :options="kindOptions"
          class="w-40"
          aria-label="形态类型"
        />
        <FieldInput
          v-model="search"
          placeholder="搜索名称或代码"
          aria-label="搜索买点"
          class="w-full sm:ml-auto sm:w-52"
        />
      </div>
      <AppApiErrorAlert
        v-if="error"
        :error="error"
      />
      <div
        v-if="loading"
        class="space-y-3"
      >
        <Skeleton
          v-for="n in 3"
          :key="n"
          class="h-10 w-full"
        />
      </div>
      <div
        v-else-if="!filtered.length"
        class="rounded-lg border border-dashed py-12 text-center"
      >
        <p class="text-sm font-medium">
          {{ data?.status === 'not_computed' ? '该日期尚无新版形态数据' : '当前筛选下没有机会' }}
        </p>
        <p class="mt-2 text-xs text-muted-foreground">
          {{ data?.status === 'not_computed' ? '历史结果不会自动重算；请等待正式任务或显式回填。' : '可切换观察状态查看形成中的结构；历史不足不视为形态不成立。' }}
        </p>
      </div>
      <div
        v-else
        class="overflow-x-auto rounded-lg border"
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-8">
                <span class="sr-only">操作</span>
              </TableHead>
              <SortableTableHeader
                v-for="[key, label] in opportunityColumns"
                :key="key"
                :label="label"
                :active="sort === key"
                :direction="direction"
                @sort="changeSort(key)"
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            <template
              v-for="item in visible"
              :key="item.code"
            >
              <TableRow
                class="cursor-pointer"
                :class="expanded === item.code ? 'bg-muted/40' : ''"
                @click="toggle(item)"
              >
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    :aria-label="`展开 ${item.name} 买点证据`"
                    :aria-expanded="expanded === item.code"
                    @click.stop="toggle(item)"
                  >
                    <ChevronDown
                      v-if="expanded === item.code"
                      class="size-3.5"
                    /><ChevronRight
                      v-else
                      class="size-3.5"
                    />
                  </Button>
                </TableCell>
                <TableCell
                  v-for="[key] in opportunityColumns"
                  :key="key"
                  class="whitespace-nowrap px-4 py-3 tabular-nums"
                >
                  <div v-if="key === 'name'">
                    <StockLink
                      :code="item.code"
                      :name="item.name"
                    />
                  </div>
                  <div v-else-if="key === 'kind'">
                    <p>{{ cell(item, key) }}</p><p
                      v-if="otherLabels(item)"
                      class="mt-1 text-xs text-muted-foreground"
                    >
                      另匹配 {{ otherLabels(item) }}
                    </p>
                  </div>
                  <Badge
                    v-else-if="key === 'status'"
                    :variant="item.primary ? 'secondary' : 'outline'"
                    class="font-normal"
                  >
                    {{ cell(item, key) }}
                  </Badge>
                  <span
                    v-else
                    :class="key === 'qualityScore' ? 'font-medium' : 'text-sm'"
                  >{{ cell(item, key) }}</span>
                </TableCell>
              </TableRow>
              <TableRow v-if="expanded === item.code">
                <TableCell
                  :colspan="10"
                  class="bg-muted/10 p-4 sm:p-6"
                >
                  <div class="mb-4 flex flex-wrap gap-2">
                    <Button
                      v-for="branch in item.branches"
                      :key="branch.structureId"
                      size="sm"
                      :variant="selected?.structureId === branch.structureId ? 'secondary' : 'ghost'"
                      @click="selected = branch"
                    >
                      {{ patternNames[branch.kind] }}<span class="text-xs text-muted-foreground">{{ opportunityStates[branch.status] }}</span>
                    </Button>
                  </div>
                  <div
                    v-if="selected"
                    class="space-y-4"
                  >
                    <div class="flex flex-wrap justify-between gap-3 text-sm">
                      <p>{{ selected.reason }}</p><span class="text-xs text-muted-foreground">背景 {{ selected.backgroundPeriods?.join(' / ') ?? '10' }} 日 · 执行 MA5/10 · {{ selected.ruleVersion }}</span>
                    </div>
                    <div class="grid gap-3 text-xs text-muted-foreground sm:grid-cols-3">
                      <span>形成 {{ selected.startDate }} → {{ selected.endDate }}</span><span>发现 {{ selected.discoveredAt }} · 首确认 {{ selected.firstConfirmedAt ?? '尚未确认' }}</span><span>数据 {{ historyLabels[item.historyStatus] ?? '无法判断' }} · 前复权</span>
                    </div>
                    <div class="grid grid-cols-2 gap-3 rounded-lg border bg-background p-3 text-xs sm:grid-cols-4">
                      <div>
                        <span class="text-muted-foreground">所选分支质量</span><p class="mt-1 font-medium tabular-nums">
                          {{ formatFixed(selected.qualityScore) }}
                        </p>
                      </div>
                      <div>
                        <span class="text-muted-foreground">触发 / 支撑</span><p class="mt-1 font-medium tabular-nums">
                          {{ formatFixed(selected.trigger) }} / {{ formatFixed(selected.support) }}
                        </p>
                      </div>
                      <div>
                        <span class="text-muted-foreground">距触发位 / ATR</span><p class="mt-1 font-medium tabular-nums">
                          {{ formatPercent(selected.distancePct) }} / {{ formatFixed(selected.distanceAtr) }}
                        </p>
                      </div>
                      <div>
                        <span class="text-muted-foreground">结构失效参考</span><p class="mt-1 font-medium tabular-nums">
                          {{ formatFixed(selected.invalidation) }}
                        </p>
                      </div>
                    </div>
                    <p
                      v-if="selected.trendBackground"
                      class="text-xs text-muted-foreground"
                    >
                      趋势质量 {{ formatFixed(selected.trendBackground.trendScore) }} · 相对强度 {{ formatFixed(selected.trendBackground.rsScore) }} · Alpha {{ formatFixed(selected.trendBackground.alphaScore) }} · 趋势排名 {{ selected.trendBackground.rank ?? '—' }}；背景指标不与形态质量相加。
                    </p>
                    <details
                      v-if="evidenceMetrics.length || selected.points.length"
                      class="rounded-lg border bg-background p-3 text-xs"
                    >
                      <summary class="cursor-pointer font-medium">
                        形态证据与可知日期
                      </summary>
                      <div class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                        <div
                          v-for="metric in evidenceMetrics"
                          :key="metric.label"
                        >
                          <span class="text-muted-foreground">{{ metric.label }}</span><p class="mt-1 tabular-nums">
                            {{ metric.value }}
                          </p>
                        </div>
                      </div>
                      <ol
                        v-if="selected.points.length"
                        class="mt-3 space-y-2 border-t pt-3 text-muted-foreground"
                      >
                        <li
                          v-for="(point, index) in selected.points"
                          :key="index"
                        >
                          波段点 {{ index + 1 }} · {{ point.date }} · {{ formatFixed(point.price) }} · 可确认 {{ point.knownDate }}
                        </li>
                      </ol>
                    </details>
                    <DailyKLineCard
                      :symbol="item.code"
                      :highlight-date="item.dataAsOf"
                      :opportunity="selected"
                    />
                    <p class="text-xs text-muted-foreground">
                      仅绘制所选后台结构；其他匹配标签不作为独立共振。结构失效参考与 ATR 风险参考不同，不是保证成交的止损价。
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{{ filtered.length }} 只证券 · 同票合并 · 每页 10 只</span><AppPagination
          :current-page="page"
          :total-pages="Math.ceil(filtered.length / 10)"
          @page-change="page = $event"
        />
      </div>
    </CardContent>
  </Card>
</template>
