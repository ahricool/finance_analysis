<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Constituent, Constituents, IndustryDetail, IndustrySnapshot } from '@/api/industryStrength';
import type { ParsedApiError } from '@/api/error';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTime } from '@/utils/format';
import { XIcon } from 'lucide-vue-next';
import {
  breadthCountsLabel,
  breadthMissingReason,
  formatAmountYi,
  formatPercent,
  formatPoints,
  formatPrice,
  formatPulse,
  formatRankDelta,
  formatScore,
  stateBadgeClass,
  stateExplanations,
  stateLabels,
  toneClass,
} from './display';

const props = defineProps<{
  previewMode?: boolean;
  open: boolean;
  name: string;
  code: string;
  snapshotDate: string | null;
  row: IndustrySnapshot | null;
  detail: IndustryDetail | null;
  constituents: Constituents | null;
  detailLoading: boolean;
  membersLoading: boolean;
  detailError: ParsedApiError | null;
  membersError: ParsedApiError | null;
  missingSelected: boolean;
}>();
const emit = defineEmits<{
  'update:open': [value: boolean];
  retryDetail: [];
  retryConstituents: [];
  dismissDetailError: [];
  dismissMembersError: [];
}>();

const matchedDetail = computed(() => {
  const current = props.detail?.current;
  if (!current) return null;
  if (current.industryCode !== props.code) return null;
  if (!props.snapshotDate || current.tradeDate !== props.snapshotDate) return null;
  return props.detail;
});
const matchingRow = computed(() => {
  if (!props.row) return null;
  if (props.row.industryCode !== props.code) return null;
  if (props.snapshotDate && props.row.tradeDate !== props.snapshotDate) return null;
  return props.row;
});
const current = computed(() => matchedDetail.value?.current ?? matchingRow.value ?? null);
const historyItems = computed(() => matchedDetail.value?.history ?? []);
const overviewItems = computed(() => {
  const row = current.value;
  if (!row) return [];
  return [
    ['5 日收益（%）', formatPercent(row.ret5D, { unit: false }), toneClass(row.ret5D)],
    ['10 日收益（%）', formatPercent(row.ret10D, { unit: false }), toneClass(row.ret10D)],
    ['20 日收益（%）', formatPercent(row.ret20D, { unit: false }), toneClass(row.ret20D)],
    ['5 日超额（百分点）', formatPoints(row.rs5D, { unit: false }), toneClass(row.rs5D)],
    ['10 日超额（百分点）', formatPoints(row.rs10D, { unit: false }), toneClass(row.rs10D)],
    ['20 日超额（百分点）', formatPoints(row.rs20D, { unit: false }), toneClass(row.rs20D)],
    ['5 日动量变化（百分点）', formatPoints(row.momentumAcceleration5D, { unit: false }), toneClass(row.momentumAcceleration5D)],
    ['成交额脉冲（×）', formatPulse(row.turnoverRatio5D, { unit: false }), ''],
    ['综合强度', formatScore(row.strengthScore), ''],
    ['1 日排名变化（名）', formatRankDelta(row.rankChange1D), toneClass(row.rankChange1D)],
    ['3 日排名变化（名）', formatRankDelta(row.rankChange3D), toneClass(row.rankChange3D)],
    ['5 日排名变化（名）', formatRankDelta(row.rankChange5D), toneClass(row.rankChange5D)],
  ] as const;
});

const columns = [
  { key: 'name', label: '股票' },
  { key: 'trendRank', label: 'Trend Rank', description: '写入当前成分数据时，最新 CN Trend Following 正式快照中的 Alpha Rank，1 为最强；不在 Trend Universe 或暂无正式数据时显示 —。不对应上方历史日期。' },
  { key: 'price', label: '收盘价' },
  { key: 'changePct', label: '涨跌幅（%）' },
  { key: 'aboveMa5', label: 'MA5' },
  { key: 'aboveMa20', label: 'MA20' },
  { key: 'amount', label: '成交额' },
] as const;
type SortKey = typeof columns[number]['key'];
const sortKey = ref<SortKey>('changePct');
const sortDirection = ref<'asc' | 'desc'>('desc');
function sortValue(item: Constituent, key: SortKey): string | number | boolean | null {
  const value = item[key];
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  return value ?? null;
}
function toggleSort(key: SortKey) {
  sortDirection.value = sortKey.value === key
    ? (sortDirection.value === 'asc' ? 'desc' : 'asc')
    : (key === 'name' || key === 'trendRank' ? 'asc' : 'desc');
  sortKey.value = key;
}
const sortedItems = computed(() => [...(props.constituents?.items ?? [])].sort((left, right) => {
  const a = sortValue(left, sortKey.value);
  const b = sortValue(right, sortKey.value);
  const tie = left.code.localeCompare(right.code);
  if (a == null) return b == null ? tie : 1;
  if (b == null) return -1;
  const comparison = typeof a === 'string' && typeof b === 'string'
    ? a.localeCompare(b, 'zh-CN') : Number(a) - Number(b);
  return comparison * (sortDirection.value === 'asc' ? 1 : -1) || tie;
}));

function ma(value: boolean | null) {
  return value == null ? '缺失' : value ? '上方' : '下方 / 持平';
}
</script>

<template>
  <Dialog
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <DialogContent
      class="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-1rem)] max-w-[calc(100%-1rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[calc(100%-2rem)] lg:max-w-6xl"
      :show-close-button="false"
      data-testid="industry-detail-dialog"
    >
      <DialogHeader class="shrink-0 space-y-2 border-b bg-popover px-5 py-4 text-left">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <DialogTitle class="flex flex-wrap items-center gap-2 text-lg">
              <span>{{ name || code }}</span>
              <span
                v-if="current"
                class="text-muted-foreground"
              >强度排名 {{ current.strengthRank }}</span>
              <span
                v-if="current"
                class="rounded-full border px-2 py-0.5 text-xs"
                :class="stateBadgeClass[current.state]"
              >{{ stateLabels[current.state] }}</span>
            </DialogTitle>
            <DialogDescription class="mt-1">
              {{ previewMode ? '盘中预览日期' : '实际查询快照日期' }} {{ snapshotDate || '—' }} · 行业详情随所选日期，不使用热力图悬浮单元格日期
            </DialogDescription>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="关闭"
            data-testid="industry-detail-close"
            class="focus-visible:ring-2 focus-visible:ring-ring"
            @click="emit('update:open', false)"
          >
            <XIcon />
          </Button>
        </div>
      </DialogHeader>
      <div class="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4">
        <p
          v-if="missingSelected"
          class="mb-4 rounded-lg border border-amber-500/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-200"
          data-testid="industry-missing-selected"
        >
          所选行业不在 {{ snapshotDate || '当前' }} 截面中，未改选其他行业。
        </p>
        <section
          class="space-y-4"
          data-testid="industry-detail-overview"
        >
          <h3 class="text-base font-semibold">
            行业概览
          </h3>
          <AppApiErrorAlert
            v-if="detailError"
            :error="detailError"
            action-label="重试行业详情"
            @action="emit('retryDetail')"
            @dismiss="emit('dismissDetailError')"
          />
          <Skeleton
            v-if="detailLoading && !current"
            class="h-48"
            data-testid="industry-detail-loading"
          />
          <p
            v-else-if="detailLoading"
            class="text-sm text-muted-foreground"
          >
            正在更新行业详情…
          </p>
          <template v-if="current">
            <p class="text-sm leading-6 text-muted-foreground">
              {{ stateExplanations[current.state] }}
            </p>
            <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
              <div
                v-for="item in overviewItems"
                :key="item[0]"
                class="rounded-lg bg-muted/50 p-3"
              >
                <p class="text-xs text-muted-foreground">
                  {{ item[0] }}
                </p>
                <p
                  class="mt-2 font-semibold tabular-nums whitespace-nowrap"
                  :class="item[2]"
                >
                  {{ item[1] }}
                </p>
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
              <div class="rounded-lg bg-muted/50 p-3">
                <p class="text-xs text-muted-foreground">
                  成分股上涨占比
                </p>
                <p class="mt-2 font-semibold tabular-nums">
                  {{ formatPercent(current.upRatio) }}
                </p>
                <p class="mt-1 text-xs text-muted-foreground">
                  {{ breadthMissingReason(current, 'up') || breadthCountsLabel(current.upCount, current.dailyValidCount, 'up') }}
                </p>
              </div>
              <div class="rounded-lg bg-muted/50 p-3">
                <p class="text-xs text-muted-foreground">
                  站上 MA5 的成分股占比
                </p>
                <p class="mt-2 font-semibold tabular-nums">
                  {{ formatPercent(current.aboveMa5Ratio) }}
                </p>
                <p class="mt-1 text-xs text-muted-foreground">
                  {{ breadthMissingReason(current, 'ma5') || breadthCountsLabel(current.aboveMa5Count, current.ma5ValidCount, 'ma') }}
                </p>
              </div>
              <div class="rounded-lg bg-muted/50 p-3">
                <p class="text-xs text-muted-foreground">
                  站上 MA20 的成分股占比
                </p>
                <p class="mt-2 font-semibold tabular-nums">
                  {{ formatPercent(current.aboveMa20Ratio) }}
                </p>
                <p class="mt-1 text-xs text-muted-foreground">
                  {{ breadthMissingReason(current, 'ma20') || breadthCountsLabel(current.aboveMa20Count, current.ma20ValidCount, 'ma') }}
                </p>
              </div>
              <div class="rounded-lg bg-muted/50 p-3">
                <p class="text-xs text-muted-foreground">
                  等权涨跌代理
                </p>
                <p
                  class="mt-2 font-semibold tabular-nums"
                  :class="toneClass(current.equalWeightReturn)"
                >
                  {{ formatPercent(current.equalWeightReturn) }}
                </p>
                <p class="mt-1 text-xs text-muted-foreground">
                  内部广度代理，不代表行业指数贡献
                </p>
              </div>
            </div>
            <p class="text-xs leading-6 text-muted-foreground">
              快照 Daily 有效成分 {{ current.dailyValidCount ?? '—' }} / {{ current.constituentCount ?? '—' }}
              · 上涨 {{ current.upCount ?? '—' }} / 下跌 {{ current.downCount ?? '—' }} / 平盘 {{ current.flatCount ?? '—' }}。
              成分观察时间：{{ formatDateTime(current.membersObservedAt) }}。历史广度为当时保存的观测值。
            </p>
          </template>
        </section>
        <section
          class="space-y-4 border-t pt-6"
          data-testid="industry-detail-history"
        >
          <h3 class="text-base font-semibold">
            历史表现
          </h3>
          <p class="text-sm text-muted-foreground">
            历史指标跟随所选快照日期 {{ snapshotDate || '—' }}，最多展示截至该日的 20 个已保存交易日。
          </p>
          <div
            v-if="historyItems.length"
            class="overflow-x-auto rounded-lg border"
          >
            <Table container-class="overflow-visible">
              <TableHeader class="sticky top-0 bg-background">
                <TableRow>
                  <TableHead
                    v-for="label in ['日期', '强度排名', '综合强度', '5 日超额（百分点）', '10 日超额（百分点）', '20 日超额（百分点）', '5 日动量（百分点）', '上涨占比（%）', 'MA5（%）', 'MA20（%）', '成交脉冲（×）']"
                    :key="label"
                  >
                    {{ label }}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="item in [...historyItems].reverse()"
                  :key="item.tradeDate"
                >
                  <TableCell class="tabular-nums">
                    {{ item.tradeDate }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ item.strengthRank }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ formatScore(item.strengthScore) }}
                  </TableCell>
                  <TableCell
                    v-for="key in (['rs5D', 'rs10D', 'rs20D', 'momentumAcceleration5D'] as const)"
                    :key="key"
                    class="tabular-nums"
                    :class="toneClass(item[key])"
                  >
                    {{ formatPoints(item[key], { unit: false }) }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ formatPercent(item.upRatio, { unit: false }) }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ formatPercent(item.aboveMa5Ratio, { unit: false }) }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ formatPercent(item.aboveMa20Ratio, { unit: false }) }}
                  </TableCell>
                  <TableCell class="tabular-nums">
                    {{ formatPulse(item.turnoverRatio5D, { unit: false }) }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
          <p
            v-else-if="detailLoading"
            class="py-10 text-center text-muted-foreground"
          >
            正在加载历史表现…
          </p>
          <p
            v-else
            class="py-10 text-center text-muted-foreground"
          >
            暂无该行业历史快照。
          </p>
        </section>
        <section
          class="space-y-4 border-t pt-6"
          data-testid="industry-detail-constituents"
        >
          <h3 class="text-base font-semibold">
            {{ previewMode ? '本次预览成分股' : '当前成分股（最新数据）' }}
          </h3>
          <div
            class="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-3"
            data-testid="industry-constituents-banner"
          >
            <p class="font-medium">
              {{ previewMode ? '本次预览生成的成分数据' : '最近一次任务生成的成分数据' }}
            </p>
            <p
              class="mt-1 text-sm"
              data-testid="industry-constituents-dates"
            >
              更新时间 {{ formatDateTime(constituents?.updatedAt) }}
            </p>
            <p class="mt-1 text-sm text-amber-800 dark:text-amber-200">
              {{ previewMode ? '与排行榜使用同一批盘中数据，成交额为盘中累计口径。' : '展示最近一次行业强度任务成功生成的最新成分股及收盘指标，不随上方历史快照日期变化。' }}
            </p>
          </div>
          <p class="text-xs leading-6 text-muted-foreground">
            {{ previewMode ? '价格为最新点位；历史前复权价格按行情昨收对齐，MA 包含今日。' : '价格为前复权收盘价。' }}Trend Rank 为写入这份最新成分数据时读取的最新 CN Trend Following 正式快照 Alpha Rank，不对应上方历史日期。
          </p>
          <p
            v-if="previewMode"
            class="text-xs text-muted-foreground"
          >
            Trend Rank 正式日期：{{ constituents?.trendRankDate || '—' }}。盘中状态可能变化，成交确认可能滞后。
          </p>
          <AppApiErrorAlert
            v-if="membersError"
            :error="membersError"
            action-label="重试当前成分"
            @action="emit('retryConstituents')"
            @dismiss="emit('dismissMembersError')"
          />
          <p
            v-if="membersLoading"
            class="text-sm text-muted-foreground"
            data-testid="industry-members-loading"
          >
            正在加载当前成分股…
          </p>
          <p
            v-if="!membersLoading && !membersError && constituents && !constituents.items.length"
            class="text-sm text-muted-foreground"
          >
            暂无已生成的成分数据，等待行业强度任务成功生成。
          </p>
          <template v-if="constituents && constituents.industryCode === code">
            <p class="text-xs text-muted-foreground">
              Daily {{ constituents.dailyValidCount }} / {{ constituents.constituentCount }}
              · MA5 {{ constituents.ma5ValidCount }} / {{ constituents.constituentCount }}
              · MA20 {{ constituents.ma20ValidCount }} / {{ constituents.constituentCount }}
              · 点击表头排序，缺失值始终排最后
            </p>
            <div class="overflow-x-auto rounded-lg border">
              <Table container-class="overflow-visible">
                <TableHeader class="sticky top-0 bg-background">
                  <TableRow>
                    <SortableTableHeader
                      v-for="column in columns"
                      :key="column.key"
                      :label="previewMode && column.key === 'price' ? '最新价' : column.label"
                      :description="'description' in column ? column.description : undefined"
                      :active="sortKey === column.key"
                      :direction="sortDirection"
                      @sort="toggleSort(column.key)"
                    />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow
                    v-for="item in sortedItems"
                    :key="item.code"
                  >
                    <TableCell>{{ item.name }} <span class="ml-2 text-xs text-muted-foreground">{{ item.code }}</span></TableCell>
                    <TableCell class="tabular-nums">
                      {{ item.trendRank == null ? '—' : `#${item.trendRank}` }}
                    </TableCell>
                    <TableCell class="tabular-nums">
                      {{ formatPrice(item.price) }}
                    </TableCell>
                    <TableCell
                      class="tabular-nums"
                      :class="toneClass(item.changePct)"
                    >
                      {{ formatPercent(item.changePct) }}
                    </TableCell>
                    <TableCell>{{ ma(item.aboveMa5) }}</TableCell>
                    <TableCell>{{ ma(item.aboveMa20) }}</TableCell>
                    <TableCell class="tabular-nums">
                      {{ formatAmountYi(item.amount) }}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </template>
        </section>
      </div>
    </DialogContent>
  </Dialog>
</template>
