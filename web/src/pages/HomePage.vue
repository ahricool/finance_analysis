<script setup lang="ts">
import { analysisApi } from '@/api/analysis';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import HistoryList from '@/components/history/HistoryList.vue';
import ReportMarkdown from '@/components/report/ReportMarkdown.vue';
import ReportSummary from '@/components/report/ReportSummary.vue';
import { useDashboardLifecycle } from '@/composables/useDashboardLifecycle';
import { useHomeDashboardState } from '@/composables/useHomeDashboardState';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { BarChart3, FileText, RefreshCw, Search } from 'lucide-vue-next';
import { computed, ref, unref, watch } from 'vue';
import { storeToRefs } from 'pinia';

type MarketReviewNotice = {
  variant: 'success' | 'warning' | 'destructive';
  title: string;
  message: string;
} | null;

const timezoneStore = useTimezoneStore();
const { displayTimezone } = storeToRefs(timezoneStore);
const isSubmittingMarketReview = ref(false);
const marketReviewNotice = ref<MarketReviewNotice>(null);
const marketReviewError = ref<ParsedApiError | null>(null);
const dashboardScrollRef = ref<HTMLElement | null>(null);

const {
  query,
  inputError,
  duplicateError,
  error,
  isAnalyzing,
  historyItems,
  isLoadingHistory,
  currentPage,
  historyTotal,
  historyTotalPages,
  selectedReport,
  isLoadingReport,
  markdownDrawerOpen,
  setQuery,
  clearError,
  loadInitialHistory,
  refreshHistory,
  goToHistoryPage,
  selectHistoryItem,
  submitAnalysis,
  openMarkdownDrawer,
  closeMarkdownDrawer,
} = useHomeDashboardState();

const reportLanguage = computed(() =>
  normalizeReportLanguage(selectedReport.value?.meta.reportLanguage),
);
const reportText = computed(() => getReportText(reportLanguage.value));

useDashboardLifecycle({
  loadInitialHistory: async () => {
    await unref(loadInitialHistory)();
  },
  refreshHistory: async (silent) => {
    await unref(refreshHistory)(silent);
  },
});

function scrollMarketReviewFeedbackIntoView() {
  const target = dashboardScrollRef.value;
  if (!target) return;
  if (typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

watch(displayTimezone, () => {
  void unref(refreshHistory)(true);
});

function handleHistoryItemClick(recordId: number) {
  void unref(selectHistoryItem)(recordId);
}

function handleSubmitAnalysisWrapper(
  stockCode?: string,
  stockName?: string,
  selectionSource?: 'manual' | 'autocomplete' | 'import' | 'image',
) {
  void unref(submitAnalysis)({
    stockCode,
    stockName,
    originalQuery: unref(query),
    selectionSource: selectionSource ?? 'manual',
  });
}

function onStockAutocompleteSubmit(
  code: string,
  name?: string,
  source?: 'manual' | 'autocomplete',
) {
  handleSubmitAnalysisWrapper(code, name, source ?? 'manual');
}

function handleReanalyze() {
  if (!selectedReport.value) return;
  void unref(submitAnalysis)({
    stockCode: selectedReport.value.meta.stockCode,
    stockName: selectedReport.value.meta.stockName,
    originalQuery: selectedReport.value.meta.stockCode,
    selectionSource: 'manual',
    forceRefresh: true,
  });
}

async function handleTriggerMarketReview() {
  isSubmittingMarketReview.value = true;
  marketReviewNotice.value = null;
  marketReviewError.value = null;
  scrollMarketReviewFeedbackIntoView();
  try {
    const result = await analysisApi.triggerMarketReview();
    const taskSuffix = result.taskId ? `（任务 ID：${result.taskId}）` : '';
    marketReviewNotice.value = {
      variant: 'success',
      title: '大盘复盘已提交',
      message: `${result.message || '任务已提交，执行结果可稍后在任务记录或日历中查看。'}${taskSuffix}`,
    };
    scrollMarketReviewFeedbackIntoView();
  } catch (err: unknown) {
    marketReviewError.value = getParsedApiError(err);
    marketReviewNotice.value = null;
    scrollMarketReviewFeedbackIntoView();
  } finally {
    isSubmittingMarketReview.value = false;
  }
}

function handleHistoryPageChange(page: number) {
  void unref(goToHistoryPage)(page);
}
</script>

<template>
  <div
    data-testid="analysis-workspace"
    class="space-y-6 py-4 sm:py-6"
  >
    <PageHeader
      title="分析"
      description="搜索标的、生成分析报告，并从历史记录继续研究。"
    />

    <Card class="border border-border shadow-sm ring-1 ring-foreground/15">
      <CardHeader class="border-b pb-4">
        <CardTitle>股票搜索</CardTitle>
        <CardDescription>输入代码或名称开始分析，也可提交大盘复盘。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3 pt-4">
        <div class="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
          <div class="min-w-0 flex-1">
            <StockAutocomplete
              :model-value="query"
              :disabled="isAnalyzing"
              placeholder="输入股票代码或名称，如 600519、贵州茅台、AAPL"
              :class="inputError ? 'border-destructive/50' : undefined"
              @update:model-value="(v: string) => unref(setQuery)(v)"
              @submit="onStockAutocompleteSubmit"
            />
          </div>
          <div class="flex shrink-0 items-center gap-2.5">
            <LoadingButton
              type="button"
              variant="secondary"
              size="default"
              :loading="isSubmittingMarketReview"
              loading-text="提交中"
              class="flex-1 whitespace-nowrap md:flex-none"
              @click="handleTriggerMarketReview"
            >
              <BarChart3
                class="h-4 w-4"
                aria-hidden="true"
              />
              大盘复盘
            </LoadingButton>
            <LoadingButton
              type="button"
              :disabled="!query || isAnalyzing"
              :loading="isAnalyzing"
              loading-text="分析中"
              variant="brand"
              class="flex-1 whitespace-nowrap md:flex-none"
              @click="handleSubmitAnalysisWrapper()"
            >
              <Search />分析
            </LoadingButton>
          </div>
        </div>

        <Alert
          v-if="inputError"
          variant="destructive"
        >
          <AlertTitle>输入有误</AlertTitle>
          <AlertDescription>{{ inputError }}</AlertDescription>
        </Alert>
        <Alert
          v-else-if="duplicateError"
          variant="warning"
        >
          <AlertTitle>任务已存在</AlertTitle>
          <AlertDescription class="text-current/80">
            {{ duplicateError }}
          </AlertDescription>
        </Alert>
      </CardContent>
    </Card>

    <div class="grid items-start gap-4 lg:grid-cols-[19rem_minmax(0,1fr)]">
      <HistoryList
        :items="historyItems"
        :is-loading="isLoadingHistory"
        :current-page="currentPage"
        :total-pages="historyTotalPages"
        :total-count="historyTotal"
        :selected-id="selectedReport?.meta.id"
        class="w-full lg:sticky lg:top-20 lg:max-h-[calc(100dvh-8rem)]"
        @item-click="handleHistoryItemClick"
        @page-change="handleHistoryPageChange"
      />

      <section
        ref="dashboardScrollRef"
        data-testid="analysis-workspace-scroll"
        class="min-w-0"
      >
        <Card class="border border-border shadow-sm ring-1 ring-foreground/15">
          <CardHeader class="border-b pb-4">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 space-y-1">
                <CardTitle>分析结果</CardTitle>
                <CardDescription>从历史记录选择报告，或搜索后生成新的分析。</CardDescription>
              </div>
              <div
                v-if="selectedReport"
                class="flex shrink-0 flex-wrap items-center justify-end gap-2"
              >
                <Button
                  variant="default"
                  size="sm"
                  :disabled="isAnalyzing || selectedReport.meta.id === undefined"
                  @click="handleReanalyze"
                >
                  <RefreshCw />
                  {{ reportText.reanalyze }}
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  :disabled="selectedReport.meta.id === undefined"
                  @click="unref(openMarkdownDrawer)()"
                >
                  <FileText />
                  {{ reportText.fullReport }}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent class="pt-4">
            <div
              v-if="marketReviewNotice"
              class="mb-3"
            >
              <Alert :variant="marketReviewNotice.variant">
                <AlertTitle>{{ marketReviewNotice.title }}</AlertTitle>
                <AlertDescription class="text-current/80">
                  {{ marketReviewNotice.message }}
                </AlertDescription>
              </Alert>
            </div>

            <div
              v-if="marketReviewError"
              class="mb-3"
            >
              <ApiErrorAlert
                :error="marketReviewError"
                class="mb-1"
                @dismiss="marketReviewError = null"
              />
            </div>

            <ApiErrorAlert
              v-if="error"
              :error="error"
              class="mb-3"
              @dismiss="() => unref(clearError)()"
            />

            <div
              v-if="isLoadingReport"
              class="grid gap-4 md:grid-cols-2"
            >
              <div
                v-for="index in 4"
                :key="index"
                class="space-y-3 rounded-lg border p-6"
              >
                <Skeleton class="h-5 w-1/3" /><Skeleton class="h-4 w-full" /><Skeleton class="h-4 w-5/6" /><Skeleton class="h-32 w-full" />
              </div>
            </div>
            <ReportSummary
              v-else-if="selectedReport"
              :data="selectedReport"
              is-history
            />
            <Empty
              v-else
              class="py-16"
            >
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BarChart3 />
                </EmptyMedia>
                <EmptyTitle>开始分析</EmptyTitle>
                <EmptyDescription>输入股票代码进行分析，或从历史记录选择报告查看。</EmptyDescription>
              </EmptyHeader>
            </Empty>
          </CardContent>
        </Card>
      </section>
    </div>

    <ReportMarkdown
      v-if="markdownDrawerOpen && selectedReport?.meta.id"
      :record-id="selectedReport.meta.id"
      :stock-name="selectedReport.meta.stockName || ''"
      :stock-code="selectedReport.meta.stockCode"
      :report-language="reportLanguage"
      @update:open="() => unref(closeMarkdownDrawer)()"
    />
  </div>
</template>
