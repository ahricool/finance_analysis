<script setup lang="ts">
import { computed } from 'vue';
import type { Constituents, IndustryDetail, IndustrySnapshot } from '@/api/industryStrength';
import type { ParsedApiError } from '@/api/error';
import type { DetailTab } from '@/composables/useIndustryStrength';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
  tab: DetailTab;
}>();
const emit = defineEmits<{
  'update:open': [value: boolean];
  'update:tab': [value: DetailTab];
  retryDetail: [];
  retryConstituents: [];
  dismissDetailError: [];
  dismissMembersError: [];
}>();

const current = computed(() => props.detail?.current ?? props.row ?? null);
const overviewItems = computed(() => {
  const row = current.value;
  if (!row) return [];
  return [
    ['5 日收益', formatPercent(row.ret5D), toneClass(row.ret5D)],
    ['10 日收益', formatPercent(row.ret10D), toneClass(row.ret10D)],
    ['20 日收益', formatPercent(row.ret20D), toneClass(row.ret20D)],
    ['5 日超额', formatPoints(row.rs5D), toneClass(row.rs5D)],
    ['10 日超额', formatPoints(row.rs10D), toneClass(row.rs10D)],
    ['20 日超额', formatPoints(row.rs20D), toneClass(row.rs20D)],
    ['5 日动量变化', formatPoints(row.momentumAcceleration5D), toneClass(row.momentumAcceleration5D)],
    ['成交额脉冲', formatPulse(row.turnoverRatio5D), ''],
    ['综合强度', formatScore(row.strengthScore), ''],
    ['1 日排名变化', formatRankDelta(row.rankChange1D), toneClass(row.rankChange1D)],
    ['3 日排名变化', formatRankDelta(row.rankChange3D), toneClass(row.rankChange3D)],
    ['5 日排名变化', formatRankDelta(row.rankChange5D), toneClass(row.rankChange5D)],
  ] as const;
});

function ma(value: boolean | null) {
  return value == null ? '缺失' : value ? '上方' : '下方 / 持平';
}
</script>

<template>
  <Sheet
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <SheetContent
      side="right"
      class="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-xl md:max-w-2xl lg:max-w-3xl"
      :show-close-button="false"
      data-testid="industry-detail"
    >
      <SheetHeader class="sticky top-0 z-10 space-y-2 border-b bg-popover px-5 py-4 text-left">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <SheetTitle class="flex flex-wrap items-center gap-2 text-lg">
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
            </SheetTitle>
            <SheetDescription class="mt-1">
              实际查询快照日期 {{ snapshotDate || '—' }} · 行业详情随所选日期，不使用热力图悬浮单元格日期
            </SheetDescription>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="关闭"
            data-testid="industry-drawer-close"
            class="focus-visible:ring-2 focus-visible:ring-ring"
            @click="emit('update:open', false)"
          >
            <XIcon />
          </Button>
        </div>
      </SheetHeader>
      <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
        <p
          v-if="missingSelected"
          class="mb-4 rounded-lg border border-amber-500/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-200"
          data-testid="industry-missing-selected"
        >
          所选行业不在 {{ snapshotDate || '当前' }} 截面中，未改选其他行业。
        </p>
        <Tabs
          :model-value="tab"
          @update:model-value="emit('update:tab', String($event) as DetailTab)"
        >
          <TabsList class="flex h-auto w-full flex-wrap justify-start">
            <TabsTrigger
              value="overview"
              data-testid="industry-detail-tab-overview"
            >
              概览
            </TabsTrigger>
            <TabsTrigger
              value="history"
              data-testid="industry-detail-tab-history"
            >
              历史表现
            </TabsTrigger>
            <TabsTrigger
              value="constituents"
              data-testid="industry-detail-tab-constituents"
            >
              当前成分股
            </TabsTrigger>
          </TabsList>
          <TabsContent
            value="overview"
            class="space-y-4 pt-4"
          >
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
              <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                <div
                  v-for="item in overviewItems"
                  :key="item[0]"
                  class="rounded-lg bg-muted/50 p-3"
                >
                  <p class="text-xs text-muted-foreground">
                    {{ item[0] }}
                  </p>
                  <p
                    class="mt-2 font-semibold tabular-nums"
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
          </TabsContent>
          <TabsContent
            value="history"
            class="space-y-3 pt-4"
          >
            <p class="text-sm text-muted-foreground">
              历史指标跟随所选快照日期 {{ snapshotDate || '—' }}，最多展示截至该日的 20 个已保存交易日。
            </p>
            <div
              v-if="detail?.history.length"
              class="max-h-[28rem] overflow-auto rounded-lg border"
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
                    v-for="item in [...detail.history].reverse()"
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
              v-else-if="!detailLoading"
              class="py-10 text-center text-muted-foreground"
            >
              暂无该行业历史快照。
            </p>
          </TabsContent>
          <TabsContent
            value="constituents"
            class="space-y-3 pt-4"
          >
            <div
              class="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-3"
              data-testid="industry-constituents-banner"
            >
              <p class="font-medium">
                当前成分股 · 最新完整交易日观察
              </p>
              <p
                class="mt-1 text-sm"
                data-testid="industry-constituents-dates"
              >
                行情日期 {{ constituents?.tradeDate || '—' }} · 成分获取时间 {{ formatDateTime(constituents?.membersObservedAt) }}
              </p>
              <p class="mt-1 text-sm text-amber-800 dark:text-amber-200">
                不随上方历史快照日期切换，也不代表历史成分。
              </p>
            </div>
            <p class="text-xs leading-6 text-muted-foreground">
              价格为前复权收盘价。当前成分股等权涨跌仅为行业内部广度代理，不代表行业指数贡献。
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
            <template v-if="constituents && constituents.industryCode === code">
              <p class="text-xs text-muted-foreground">
                Daily {{ constituents.dailyValidCount }} / {{ constituents.constituentCount }}
                · MA5 {{ constituents.ma5ValidCount }} / {{ constituents.constituentCount }}
                · MA20 {{ constituents.ma20ValidCount }} / {{ constituents.constituentCount }}
                · 按涨跌幅降序，缺失排最后
              </p>
              <div class="max-h-80 overflow-auto rounded-lg border">
                <Table container-class="overflow-visible">
                  <TableHeader class="sticky top-0 bg-background">
                    <TableRow>
                      <TableHead
                        v-for="label in ['股票', '收盘价', '涨跌幅（%）', 'MA5', 'MA20', '成交额']"
                        :key="label"
                      >
                        {{ label }}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow
                      v-for="item in constituents.items"
                      :key="item.code"
                    >
                      <TableCell>{{ item.name }} <span class="ml-2 text-xs text-muted-foreground">{{ item.code }}</span></TableCell>
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
          </TabsContent>
        </Tabs>
      </div>
    </SheetContent>
  </Sheet>
</template>
