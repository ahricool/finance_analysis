<script setup lang="ts">
import { etfRotationApi } from '@/api/etfRotation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { ETFDetailResponse, ETFMarket, ETFMomentumSnapshot, ETFState } from '@/types/etfRotation';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { ArrowDown, ArrowUp, ArrowUpDown, RefreshCcw } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { toast } from 'vue-sonner';

type SortDirection = 'asc' | 'desc';
type SortKey = keyof Pick<
  ETFMomentumSnapshot,
  | 'rank5D' | 'code' | 'name' | 'category' | 'theme' | 'state'
  | 'ret1D' | 'ret5D' | 'ret10D' | 'ret20D' | 'ret30D' | 'ret60D'
  | 'rankChange5D' | 'momentumScore' | 'entryScore' | 'overheated'
>;

const items = ref<ETFMomentumSnapshot[]>([]);
const candidates = ref<ETFMomentumSnapshot[]>([]);
const summary = ref({
  tradeDate: '', universeSize: 0, dataReadyCount: 0, dataCoverage: 0,
  rankableSize: 0, rankableCoverage: 0, generatedAt: null as string | null, warnings: [] as string[],
});
const selectedDate = ref('');
const availableDates = ref<string[]>([]);
const loading = ref(true);
const runLoading = ref(false);
const error = ref<ParsedApiError | null>(null);
const sortKey = ref<SortKey>('entryScore');
const sortDirection = ref<SortDirection>('desc');
const selectedSort = ref<SortKey>('entryScore');
const selected = ref<ETFDetailResponse | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const market = ref<ETFMarket>('CN');
let loadGeneration = 0;

const sortOptions: Array<{ value: SortKey; label: string }> = [
  { value: 'entryScore', label: 'Entry Score' },
  { value: 'momentumScore', label: 'Momentum' },
  { value: 'ret1D', label: '1D' }, { value: 'ret5D', label: '5D' },
  { value: 'ret10D', label: '10D' }, { value: 'ret20D', label: '20D' },
  { value: 'ret30D', label: '30D' }, { value: 'ret60D', label: '60D' },
];

const sortedItems = computed(() => [...items.value].sort((left, right) => {
  const a = left[sortKey.value];
  const b = right[sortKey.value];
  if (a === b) return left.code.localeCompare(right.code);
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  const result = typeof a === 'number' && typeof b === 'number'
    ? a - b
    : String(a).localeCompare(String(b), 'zh-CN');
  return sortDirection.value === 'asc' ? result : -result;
}));

function setSort(key: SortKey) {
  if (sortKey.value === key) sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc';
  else {
    sortKey.value = key;
    sortDirection.value = ['code', 'name', 'category', 'theme', 'state'].includes(key) ? 'asc' : 'desc';
  }
}

watch(selectedSort, (value) => {
  sortKey.value = value;
  sortDirection.value = 'desc';
});

watch(market, () => {
  selected.value = null;
  selectedDate.value = '';
  availableDates.value = [];
  void load({ refreshDates: true });
});

function sortIcon(key: SortKey) {
  if (sortKey.value !== key) return ArrowUpDown;
  return sortDirection.value === 'asc' ? ArrowUp : ArrowDown;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

function score(value: number): string { return value.toFixed(1); }
function rankChange(value: number | null): string { return value === null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
function returnClass(value: number): string { return value > 0 ? 'text-destructive' : value < 0 ? 'text-success' : ''; }
function changeClass(value: number | null): string { return value && value > 0 ? 'text-destructive' : value && value < 0 ? 'text-success' : ''; }

function stateVariant(state: ETFState): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (state === 'STRONG' || state === 'EMERGING') return 'destructive';
  if (state === 'TRENDING') return 'default';
  if (state === 'COOLING' || state === 'EXHAUSTED') return 'warning';
  if (state === 'WEAK') return 'success';
  return 'info';
}

async function load(options: { refreshDates?: boolean } = {}) {
  const generation = ++loadGeneration;
  const requestedMarket = market.value;
  const requestedDate = selectedDate.value;
  loading.value = true;
  error.value = null;
  try {
    if (options.refreshDates || !availableDates.value.length) {
      const dates = await etfRotationApi.dates(requestedMarket);
      if (generation !== loadGeneration) return;
      availableDates.value = dates.items;
    }
    const ranking = await etfRotationApi.ranking(requestedMarket, requestedDate || undefined);
    if (generation !== loadGeneration) return;
    Object.assign(summary.value, ranking);
    if (!selectedDate.value) selectedDate.value = ranking.tradeDate;
    items.value = ranking.items;
    const candidatePayload = await etfRotationApi.candidates(requestedMarket, ranking.tradeDate);
    if (generation !== loadGeneration) return;
    candidates.value = candidatePayload.items;
  } catch (err) {
    if (generation !== loadGeneration) return;
    error.value = getParsedApiError(err);
    items.value = [];
    candidates.value = [];
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

function selectDate(value: string) {
  if (value === selectedDate.value) return;
  selectedDate.value = value;
  void load();
}

function refresh() {
  void load({ refreshDates: true });
}

async function runRotation() {
  runLoading.value = true;
  try {
    const accepted = await etfRotationApi.run(market.value);
    toast.success(`任务已提交：${accepted.taskId}`);
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    runLoading.value = false;
  }
}

async function openDetail(item: ETFMomentumSnapshot) {
  detailLoading.value = true;
  detailError.value = null;
  selected.value = { market: market.value, metadata: item, latest: item, history: [] };
  try {
    selected.value = await etfRotationApi.detail(item.code, market.value);
  } catch (err) {
    detailError.value = getParsedApiError(err);
  } finally {
    detailLoading.value = false;
  }
}

onMounted(() => { void load({ refreshDates: true }); });
</script>

<template>
  <div class="min-w-0 space-y-4">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold tracking-tight">
          ETF 动量轮动
        </h2>
        <p class="mt-1 text-xs leading-5 text-muted-foreground">
          收盘后基于固定 {{ market === 'CN' ? 'A 股' : '美股' }} ETF Universe 生成可解释的横截面动量排名与候选。
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <NativeSelect
          v-model="market"
          size="sm"
          aria-label="市场"
        >
          <NativeSelectOption value="CN">
            A股
          </NativeSelectOption>
          <NativeSelectOption value="US">
            美股
          </NativeSelectOption>
        </NativeSelect>
        <AppDatePicker
          :model-value="selectedDate"
          label="交易日"
          placeholder="选择交易日"
          :available-dates="availableDates"
          :clearable="false"
          :disabled="loading"
          class="w-56"
          data-testid="etf-rotation-date"
          @update:model-value="selectDate"
        />
        <Button
          variant="outline"
          size="sm"
          :disabled="loading"
          @click="refresh"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <LoadingButton
          size="sm"
          :loading="runLoading"
          loading-text="提交中…"
          @click="runRotation"
        >
          手动运行
        </LoadingButton>
      </div>
    </header>

    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="grid gap-3 sm:grid-cols-3 xl:grid-cols-6"
    >
      <Skeleton
        v-for="index in 6"
        :key="index"
        class="h-20"
      />
    </div>
    <div
      v-else
      class="grid gap-3 sm:grid-cols-3 xl:grid-cols-6"
    >
      <Card>
        <CardHeader class="pb-2">
          <CardDescription>Trade Date</CardDescription><CardTitle
            class="text-base"
            data-testid="etf-rotation-trade-date"
          >
            {{ summary.tradeDate || '—' }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader class="pb-2">
          <CardDescription>Data Coverage</CardDescription><CardTitle class="text-base">
            {{ summary.dataReadyCount }}/{{ summary.universeSize }} · {{ (summary.dataCoverage * 100).toFixed(1) }}%
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader class="pb-2">
          <CardDescription>Universe Size</CardDescription><CardTitle class="text-base">
            {{ summary.universeSize }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader class="pb-2">
          <CardDescription>Rankable Size</CardDescription><CardTitle class="text-base">
            {{ summary.rankableSize }} · {{ (summary.rankableCoverage * 100).toFixed(1) }}%
          </CardTitle>
        </CardHeader>
      </Card>
      <Card class="sm:col-span-2">
        <CardHeader class="pb-2">
          <CardDescription>Generated At</CardDescription><CardTitle class="text-base">
            {{ formatDateTimeInDisplayTimezone(summary.generatedAt) }}
          </CardTitle>
        </CardHeader>
      </Card>
    </div>

    <Alert
      v-for="warning in summary.warnings"
      :key="warning"
      variant="warning"
    >
      <AlertTitle>数据覆盖提醒</AlertTitle><AlertDescription>{{ warning }}</AlertDescription>
    </Alert>

    <Card>
      <CardHeader><CardTitle>Buy Candidates</CardTitle><CardDescription>按 Entry Score 排序，并限制每个 risk group 最多 2 只；WEAK 与 EXHAUSTED 已排除。</CardDescription></CardHeader>
      <CardContent>
        <div
          v-if="candidates.length"
          class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
        >
          <button
            v-for="item in candidates"
            :key="item.code"
            class="rounded-lg border p-3 text-left transition-colors hover:bg-muted/50"
            @click="openDetail(item)"
          >
            <div class="flex items-center justify-between">
              <span class="font-medium">#{{ item.candidateRank }} {{ item.name }}</span><Badge :variant="stateVariant(item.state)">
                {{ item.state }}
              </Badge>
            </div>
            <div class="mt-2 text-xs text-muted-foreground">
              {{ item.code }} · {{ item.riskGroup }}
            </div>
            <div class="mt-3 flex justify-between text-sm">
              <span>Entry <strong>{{ score(item.entryScore) }}</strong></span><span>Momentum <strong>{{ score(item.momentumScore) }}</strong></span>
            </div>
          </button>
        </div>
        <Empty v-else>
          <EmptyHeader><EmptyTitle>暂无候选</EmptyTitle><EmptyDescription>当前 snapshot 没有符合风险约束的 Buy Candidate。</EmptyDescription></EmptyHeader>
        </Empty>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex-row flex-wrap items-center justify-between gap-3">
        <div><CardTitle>完整排名</CardTitle><CardDescription>点击任意列标题进行本地排序，点击 ETF 查看评分拆解与历史。</CardDescription></div><NativeSelect
          v-model="selectedSort"
          size="sm"
          aria-label="默认排序"
        >
          <NativeSelectOption
            v-for="option in sortOptions"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </NativeSelectOption>
        </NativeSelect>
      </CardHeader>
      <CardContent class="px-0">
        <ScrollArea class="w-full">
          <Table class="min-w-[1500px]">
            <TableHeader>
              <TableRow>
                <TableHead
                  v-for="column in ([['rank5D','Rank'],['code','ETF Code'],['name','ETF Name'],['category','Category'],['theme','Theme'],['state','State'],['ret1D','1D'],['ret5D','5D'],['ret10D','10D'],['ret20D','20D'],['ret30D','30D'],['ret60D','60D'],['rankChange5D','5D Rank Δ'],['momentumScore','Momentum'],['entryScore','Entry'],['overheated','Overheated']] as Array<[SortKey,string]>)"
                  :key="column[0]"
                >
                  <button
                    class="inline-flex items-center gap-1 whitespace-nowrap"
                    @click="setSort(column[0])"
                  >
                    {{ column[1] }}<component
                      :is="sortIcon(column[0])"
                      class="size-3"
                    />
                  </button>
                </TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="item in sortedItems"
                :key="item.code"
                class="cursor-pointer"
                @click="openDetail(item)"
              >
                <TableCell>#{{ item.rank5D }}</TableCell><TableCell class="font-mono text-xs">
                  {{ item.code }}
                </TableCell><TableCell class="font-medium">
                  {{ item.name }}
                </TableCell><TableCell>{{ item.category }}</TableCell><TableCell>{{ item.theme }}</TableCell><TableCell>
                  <Badge :variant="stateVariant(item.state)">
                    {{ item.state }}
                  </Badge>
                </TableCell>
                <TableCell
                  v-for="key in (['ret1D','ret5D','ret10D','ret20D','ret30D','ret60D'] as const)"
                  :key="key"
                  :class="returnClass(item[key])"
                >
                  {{ pct(item[key]) }}
                </TableCell>
                <TableCell :class="changeClass(item.rankChange5D)">
                  {{ rankChange(item.rankChange5D) }}
                </TableCell><TableCell class="font-semibold">
                  {{ score(item.momentumScore) }}
                </TableCell><TableCell class="font-semibold text-primary">
                  {{ score(item.entryScore) }}
                </TableCell><TableCell>
                  <Badge :variant="item.overheated ? 'warning' : 'outline'">
                    {{ item.overheated ? '是' : '否' }}
                  </Badge>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table><template #horizontal-scrollbar>
            <ScrollBar orientation="horizontal" />
          </template>
        </ScrollArea>
      </CardContent>
    </Card>

    <Sheet
      :open="selected !== null"
      @update:open="(open) => { if (!open) selected = null; }"
    >
      <SheetContent
        side="right"
        class="w-full overflow-y-auto sm:max-w-3xl"
      >
        <SheetHeader><SheetTitle>{{ selected?.metadata.name }} · {{ selected?.metadata.code }}</SheetTitle><SheetDescription>{{ selected?.metadata.category }} / {{ selected?.metadata.theme }} · {{ selected?.metadata.riskGroup }}</SheetDescription></SheetHeader>
        <div class="space-y-5 p-4">
          <AppApiErrorAlert
            v-if="detailError"
            :error="detailError"
          /><Skeleton
            v-if="detailLoading"
            class="h-40"
          /><template v-else-if="selected">
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Card>
                <CardHeader class="pb-2">
                  <CardDescription>State</CardDescription><Badge :variant="stateVariant(selected.latest.state)">
                    {{ selected.latest.state }}
                  </Badge>
                </CardHeader>
              </Card><Card>
                <CardHeader class="pb-2">
                  <CardDescription>Momentum</CardDescription><CardTitle>{{ score(selected.latest.momentumScore) }}</CardTitle>
                </CardHeader>
              </Card><Card>
                <CardHeader class="pb-2">
                  <CardDescription>Entry</CardDescription><CardTitle>{{ score(selected.latest.entryScore) }}</CardTitle>
                </CardHeader>
              </Card><Card>
                <CardHeader class="pb-2">
                  <CardDescription>5D Rank</CardDescription><CardTitle>#{{ selected.latest.rank5D }} ({{ rankChange(selected.latest.rankChange5D) }})</CardTitle>
                </CardHeader>
              </Card>
            </div>
            <Card>
              <CardHeader><CardTitle>Score Components</CardTitle></CardHeader><CardContent>
                <div class="grid gap-2 sm:grid-cols-2">
                  <div
                    v-for="(value,key) in selected.latest.scoreComponents"
                    :key="key"
                    class="flex justify-between rounded border px-3 py-2 text-sm"
                  >
                    <span class="text-muted-foreground">{{ key }}</span><strong>{{ Number(value).toFixed(1) }}</strong>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>最近 Snapshot 历史</CardTitle></CardHeader><CardContent class="px-0">
                <Table>
                  <TableHeader><TableRow><TableHead>日期</TableHead><TableHead>5D Rank</TableHead><TableHead>Momentum</TableHead><TableHead>Entry</TableHead><TableHead>State</TableHead></TableRow></TableHeader><TableBody>
                    <TableRow
                      v-for="row in selected.history"
                      :key="row.tradeDate"
                    >
                      <TableCell>{{ row.tradeDate }}</TableCell><TableCell>#{{ row.rank5D }}</TableCell><TableCell>{{ score(row.momentumScore) }}</TableCell><TableCell>{{ score(row.entryScore) }}</TableCell><TableCell>
                        <Badge :variant="stateVariant(row.state)">
                          {{ row.state }}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </template>
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>
