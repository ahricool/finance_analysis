<script setup lang="ts">
import { onMounted } from 'vue';
import { useIndustryStrength } from '@/composables/useIndustryStrength';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import IndustryRankingTable from '@/components/industry-strength/IndustryRankingTable.vue';
import IndustryMatrixChart from '@/components/industry-strength/IndustryMatrixChart.vue';
import IndustryRankHeatmap from '@/components/industry-strength/IndustryRankHeatmap.vue';
import IndustryDetailDrawer from '@/components/industry-strength/IndustryDetailDrawer.vue';
import {
  coverageInsufficient,
  formatPoints,
  formatScore,
  methodologyLines,
} from '@/components/industry-strength/display';
import { formatDateTime } from '@/utils/format';

const page = useIndustryStrength();
const {
  ranking, chartHistory, matchedDetail, constituents, dates, requestedDate, selected, selectedLabel,
  drawerOpen, missingSelected, view, detailTab, loading, refreshing, dateSwitching,
  historyLoading, detailLoading, membersLoading, stale, error, refreshError,
  dateError, historyError, datesError, detailError, membersError, rows, summary, snapshotMeta,
  actualTradeDate, latestMode, staleLatest, historyMembersUnavailable, selectedRow,
  loadRanking, openIndustry, setDrawerOpen, setDetailTab, retryRanking, retryHistory,
  retryDetail, retryConstituents, retryDates, goLatest, changeDate, refresh,
} = page;

onMounted(() => loadRanking('initial'));
</script>

<template>
  <div
    class="min-w-0 space-y-4 overflow-x-hidden"
    data-testid="industry-strength-page"
  >
    <PageHeader
      title="行业强度"
      description="发现行业、比较强弱与变化，并查看原因和内部广度。综合强度与状态描述 A 股行业环境，不构成买卖建议。"
    >
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <AppDatePicker
            :model-value="requestedDate"
            class="w-56"
            data-testid="industry-date-picker"
            :placeholder="actualTradeDate ? `最新 · ${actualTradeDate}` : '最新快照'"
            :available-dates="dates"
            @update:model-value="changeDate"
          />
          <Button
            v-if="!latestMode"
            variant="outline"
            data-testid="industry-go-latest"
            @click="goLatest"
          >
            回到最新
          </Button>
          <TooltipProvider :delay-duration="150">
            <Tooltip>
              <TooltipTrigger as-child>
                <LoadingButton
                  variant="outline"
                  :loading="refreshing"
                  loading-text="更新中…"
                  data-testid="industry-refresh"
                  aria-label="刷新已生成快照"
                  @click="refresh"
                >
                  刷新
                </LoadingButton>
              </TooltipTrigger>
              <TooltipContent>重新读取已生成快照，不会触发重新计算</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </template>
    </PageHeader>

    <section
      v-if="ranking || loading"
      class="rounded-md border px-3 py-2 text-sm"
      data-testid="industry-data-status"
    >
      <dl class="flex flex-wrap gap-x-5 gap-y-1">
        <div class="flex gap-2">
          <dt class="text-muted-foreground">
            快照
          </dt>
          <dd data-testid="industry-snapshot-kind">
            正式收盘
          </dd>
        </div>
        <div class="flex gap-2">
          <dt class="text-muted-foreground">
            数据有效日期
          </dt>
          <dd
            class="font-medium tabular-nums"
            data-testid="industry-trade-date"
          >
            {{ actualTradeDate || '—' }}
          </dd>
        </div>
        <div class="flex gap-2">
          <dt class="text-muted-foreground">
            生成/更新
          </dt>
          <dd class="tabular-nums">
            {{ formatDateTime(snapshotMeta?.updatedAt) }}
          </dd>
        </div>
        <div class="flex gap-2">
          <dt class="text-muted-foreground">
            行业覆盖
          </dt>
          <dd
            class="tabular-nums"
            data-testid="industry-coverage"
          >
            {{ snapshotMeta ? `${snapshotMeta.quality.rankedCount} / ${snapshotMeta.quality.catalogCount}` : '—' }}
          </dd>
        </div>
      </dl>
      <p
        v-if="refreshing"
        class="mt-2 text-xs text-muted-foreground"
        data-testid="industry-refreshing"
      >
        正在重新读取已生成快照…
      </p>
      <p
        v-if="dateSwitching || dateError"
        class="mt-2 text-xs text-muted-foreground"
        data-testid="industry-date-pending"
      >
        {{ dateSwitching ? '正在加载' : '未能加载' }} {{ requestedDate || '最新快照' }}；以下内容仍对应 {{ actualTradeDate || '上一成功日期' }}。
      </p>
      <p
        v-if="stale"
        class="mt-2 rounded-md border border-amber-500/40 px-2 py-1 text-amber-800 dark:text-amber-200"
        data-testid="industry-stale"
      >
        刷新失败，仍在展示上一次成功数据（{{ actualTradeDate }}）。
      </p>
      <p
        v-if="staleLatest"
        class="mt-2 rounded-md border border-amber-500/40 px-2 py-1 text-amber-800 dark:text-amber-200"
      >
        最新完整交易日为 {{ ranking?.expectedTradeDate }}，当前展示 {{ ranking?.tradeDate }} 的已保存结果。
      </p>
      <p
        v-if="historyMembersUnavailable"
        class="mt-2 rounded-md border border-amber-500/40 px-2 py-1 text-amber-800 dark:text-amber-200"
      >
        历史补算：按当前行业目录计算所选日指数强度；缺少当日成分记录，历史广度不可用。
      </p>
      <p
        v-if="rows.some(coverageInsufficient)"
        class="mt-2 rounded-md border border-amber-500/40 px-2 py-1 text-amber-800 dark:text-amber-200"
      >
        部分行业成分覆盖不足，对应广度比例显示为不可用，不会改写综合强度或排名。
      </p>
      <details class="mt-2 text-xs leading-6 text-muted-foreground">
        <summary class="cursor-pointer text-sm text-foreground">
          口径说明
        </summary>
        <p
          v-for="line in methodologyLines"
          :key="line"
          class="mt-1"
        >
          {{ line }}
        </p>
        <p
          v-if="snapshotMeta && Object.keys(snapshotMeta.quality.excluded).length"
          class="mt-2"
        >
          未参与排名：
          <span
            v-for="(reason, code) in snapshotMeta.quality.excluded"
            :key="code"
          >{{ code }}（{{ reason }}） </span>
        </p>
      </details>
    </section>

    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重新加载"
      @action="retryRanking"
      @dismiss="error = null"
    />
    <AppApiErrorAlert
      v-if="refreshError"
      :error="refreshError"
      action-label="重试刷新"
      @action="refresh"
      @dismiss="refreshError = null"
    />
    <AppApiErrorAlert
      v-if="dateError"
      :error="dateError"
      action-label="重试该日期"
      @action="retryRanking"
      @dismiss="dateError = null"
    />
    <AppApiErrorAlert
      v-if="datesError"
      :error="datesError"
      action-label="重试日期列表"
      @action="retryDates"
      @dismiss="datesError = null"
    />
    <AppApiErrorAlert
      v-if="historyError"
      :error="historyError"
      action-label="重试排名历史"
      @action="retryHistory"
      @dismiss="historyError = null"
    />

    <div
      v-if="loading && !ranking"
      class="grid grid-cols-2 gap-3 xl:grid-cols-4"
      data-testid="industry-loading"
    >
      <Skeleton
        v-for="i in 4"
        :key="i"
        class="h-28"
      />
      <Skeleton class="col-span-2 h-80 xl:col-span-4" />
    </div>
    <p
      v-else-if="ranking && !rows.length"
      class="rounded-xl border py-16 text-center text-muted-foreground"
      data-testid="industry-empty"
    >
      所选日期暂无行业强度快照。正式结果由收盘任务生成，覆盖不足时不会发布。
    </p>

    <template v-if="rows.length">
      <div
        class="grid grid-cols-2 gap-3 xl:grid-cols-4"
        data-testid="industry-summary"
      >
        <Card class="min-w-0 p-0">
          <button
            type="button"
            class="h-full w-full text-left focus-visible:ring-2 focus-visible:ring-ring"
            :disabled="!summary.strongest"
            data-testid="industry-summary-strongest"
            @click="summary.strongest && openIndustry(summary.strongest.industryCode)"
          >
            <CardContent class="pt-4">
              <p class="text-xs text-muted-foreground">
                最强行业
              </p>
              <p class="my-2 text-lg font-semibold">
                {{ summary.strongest?.industryName ?? '—' }}
              </p>
              <p class="text-sm tabular-nums text-muted-foreground">
                综合强度 {{ summary.strongest ? formatScore(summary.strongest.strengthScore) : '—' }}
              </p>
            </CardContent>
          </button>
        </Card>
        <Card class="min-w-0 p-0">
          <button
            type="button"
            class="h-full w-full text-left focus-visible:ring-2 focus-visible:ring-ring"
            :disabled="!summary.accelerating"
            data-testid="industry-summary-accelerating"
            @click="summary.accelerating && openIndustry(summary.accelerating.industryCode)"
          >
            <CardContent class="pt-4">
              <p class="text-xs text-muted-foreground">
                加速最快
              </p>
              <p class="my-2 text-lg font-semibold">
                {{ summary.accelerating?.industryName ?? '暂无' }}
              </p>
              <p class="text-sm tabular-nums text-muted-foreground">
                {{ summary.accelerating ? formatPoints(summary.accelerating.momentumAcceleration5D) : '无正值动量变化' }}
              </p>
            </CardContent>
          </button>
        </Card>
        <Card class="min-w-0 p-0">
          <button
            type="button"
            class="h-full w-full text-left focus-visible:ring-2 focus-visible:ring-ring"
            :disabled="!summary.decelerating"
            data-testid="industry-summary-decelerating"
            @click="summary.decelerating && openIndustry(summary.decelerating.industryCode)"
          >
            <CardContent class="pt-4">
              <p class="text-xs text-muted-foreground">
                动量降速最大
              </p>
              <p class="my-2 text-lg font-semibold">
                {{ summary.decelerating?.industryName ?? '暂无' }}
              </p>
              <p class="text-sm tabular-nums text-muted-foreground">
                {{ summary.decelerating ? formatPoints(summary.decelerating.momentumAcceleration5D) : '无负值动量变化' }}
              </p>
            </CardContent>
          </button>
        </Card>
        <Card
          class="min-w-0"
          data-testid="industry-summary-advancing"
        >
          <CardContent class="pt-4">
            <p class="text-xs text-muted-foreground">
              上涨行业占比
            </p>
            <p class="my-2 text-lg font-semibold tabular-nums">
              {{ summary.advancingLabel }}
            </p>
            <p class="text-sm text-muted-foreground">
              按行业指数当日收益，不含成分股上涨广度
            </p>
          </CardContent>
        </Card>
      </div>

      <Tabs
        :model-value="view"
        class="min-w-0"
        data-testid="industry-views"
        @update:model-value="view = ($event as 'ranking' | 'matrix' | 'history')"
      >
        <TabsList class="flex h-auto w-full flex-wrap justify-start">
          <TabsTrigger
            value="ranking"
            data-testid="industry-view-ranking"
          >
            行业排行
          </TabsTrigger>
          <TabsTrigger
            value="matrix"
            data-testid="industry-view-matrix"
          >
            强度矩阵
          </TabsTrigger>
          <TabsTrigger
            value="history"
            data-testid="industry-view-history"
          >
            排名历史
          </TabsTrigger>
        </TabsList>
        <TabsContent
          value="ranking"
          force-mount
          :class="view === 'ranking' ? 'pt-4' : 'hidden'"
        >
          <IndustryRankingTable
            :rows="rows"
            :selected="selected"
            @select="openIndustry"
          />
        </TabsContent>
        <TabsContent
          value="matrix"
          force-mount
          :hidden="view !== 'matrix'"
          :class="view === 'matrix' ? 'pt-4' : 'hidden'"
        >
          <IndustryMatrixChart
            :rows="rows"
            :selected="selected"
            :active="view === 'matrix'"
            @select="openIndustry"
          />
        </TabsContent>
        <TabsContent
          value="history"
          force-mount
          :class="view === 'history' ? 'pt-4' : 'hidden'"
        >
          <p
            v-if="historyLoading"
            class="mb-2 text-sm text-muted-foreground"
            data-testid="industry-history-loading"
          >
            正在加载排名历史…
          </p>
          <h2 class="text-lg font-semibold">
            所选日 Top20 · 历史强度排名
          </h2>
          <IndustryRankHeatmap
            v-if="chartHistory.dates.length || !historyLoading"
            class="mt-3"
            :rows="rows"
            :history="chartHistory"
            :selected="selected"
            :active="view === 'history'"
            @select="openIndustry"
          />
        </TabsContent>
      </Tabs>
    </template>

    <IndustryDetailDrawer
      :open="drawerOpen"
      :name="selectedLabel"
      :code="selected"
      :snapshot-date="actualTradeDate"
      :row="selectedRow"
      :detail="matchedDetail"
      :constituents="constituents"
      :detail-loading="detailLoading"
      :members-loading="membersLoading"
      :detail-error="detailError"
      :members-error="membersError"
      :missing-selected="missingSelected"
      :tab="detailTab"
      @update:open="setDrawerOpen"
      @update:tab="setDetailTab"
      @retry-detail="retryDetail"
      @retry-constituents="retryConstituents"
      @dismiss-detail-error="detailError = null"
      @dismiss-members-error="membersError = null"
    />
  </div>
</template>
