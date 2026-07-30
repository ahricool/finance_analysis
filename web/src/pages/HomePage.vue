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
import { Card, CardContent } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { BarChart3, FileText, History, MessageCircle, RefreshCw, Search } from 'lucide-vue-next';
import { computed, ref, unref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useRouter } from 'vue-router';

type MarketReviewNotice = {
  variant: 'success' | 'warning' | 'destructive';
  title: string;
  message: string;
} | null;

const router = useRouter();
const timezoneStore = useTimezoneStore();
const { displayTimezone } = storeToRefs(timezoneStore);
const sidebarOpen = ref(false);
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
  const scrollContainer = dashboardScrollRef.value;
  if (!scrollContainer) return;
  if (typeof scrollContainer.scrollTo === 'function') {
    scrollContainer.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  scrollContainer.scrollTop = 0;
}

watch(displayTimezone, () => {
  void unref(refreshHistory)(true);
});

function handleHistoryItemClick(recordId: number) {
  void unref(selectHistoryItem)(recordId);
  sidebarOpen.value = false;
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

function handleAskFollowUp() {
  if (selectedReport.value?.meta.id === undefined) return;
  const code = selectedReport.value.meta.stockCode;
  const name = selectedReport.value.meta.stockName;
  const rid = selectedReport.value.meta.id;
  router.push(
    `/chat?stock=${encodeURIComponent(code)}&name=${encodeURIComponent(name)}&recordId=${rid}`,
  );
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
    class="flex h-[calc(100dvh-3.5rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] w-full flex-col gap-4 overflow-hidden py-4"
  >
    <PageHeader
      title="股票分析"
      description="搜索标的、生成分析报告，并从历史记录继续研究。"
    >
      <template #actions>
        <Button
          class="md:hidden"
          variant="outline"
          size="sm"
          @click="sidebarOpen = true"
        >
          <History />历史记录
        </Button>
      </template>
    </PageHeader>

    <Card class="shrink-0 py-0">
      <CardContent class="p-4">
        <div class="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
          <div class="flex min-w-0 flex-1 items-center gap-2.5">
            <div class="relative min-w-0 flex-1">
              <StockAutocomplete
                :model-value="query"
                :disabled="isAnalyzing"
                placeholder="输入股票代码或名称，如 600519、贵州茅台、AAPL"
                :class="inputError ? 'border-destructive/50' : undefined"
                @update:model-value="(v: string) => unref(setQuery)(v)"
                @submit="onStockAutocompleteSubmit"
              />
            </div>
          </div>
          <div class="flex min-w-0 flex-shrink-0 items-center gap-2.5">
            <LoadingButton
              type="button"
              variant="secondary"
              size="default"
              :loading="isSubmittingMarketReview"
              loading-text="提交中"
              class="h-10 flex-1 whitespace-nowrap md:flex-none"
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
              class="h-10 flex-1 whitespace-nowrap md:flex-none"
              @click="handleSubmitAnalysisWrapper()"
            >
              <Search />分析
            </LoadingButton>
          </div>
        </div>
      </CardContent>
    </Card>

    <div
      v-if="inputError || duplicateError"
    >
      <Alert
        v-if="inputError"
        variant="destructive"
      >
        <AlertTitle>输入有误</AlertTitle><AlertDescription>{{ inputError }}</AlertDescription>
      </Alert>
      <Alert
        v-else-if="duplicateError"
        class="border-warning/30 text-warning"
      >
        <AlertTitle>任务已存在</AlertTitle><AlertDescription class="text-current/80">
          {{ duplicateError }}
        </AlertDescription>
      </Alert>
    </div>

    <div class="flex min-h-0 flex-1 overflow-hidden">
      <div class="hidden w-[clamp(18rem,22vw,22rem)] shrink-0 self-start pb-4 pl-4 md:flex">
        <div class="flex w-full flex-col gap-3">
          <HistoryList
            :items="historyItems"
            :is-loading="isLoadingHistory"
            :current-page="currentPage"
            :total-pages="historyTotalPages"
            :total-count="historyTotal"
            :selected-id="selectedReport?.meta.id"
            fit-height
            class="w-full overflow-hidden"
            @item-click="handleHistoryItemClick"
            @page-change="handleHistoryPageChange"
          />
        </div>
      </div>

      <Sheet v-model:open="sidebarOpen">
        <SheetContent
          side="left"
          class="flex w-[min(92vw,24rem)] flex-col p-0"
        >
          <SheetHeader class="p-4 text-left">
            <SheetTitle>历史分析</SheetTitle>
            <SheetDescription>选择一份历史报告继续查看或追问。</SheetDescription>
          </SheetHeader>
          <Separator />
          <HistoryList
            :items="historyItems"
            :is-loading="isLoadingHistory"
            :current-page="currentPage"
            :total-pages="historyTotalPages"
            :total-count="historyTotal"
            :selected-id="selectedReport?.meta.id"
            class="min-h-0 flex-1 rounded-none border-0 shadow-none"
            @item-click="handleHistoryItemClick"
            @page-change="handleHistoryPageChange"
          />
        </SheetContent>
      </Sheet>

      <section
        ref="dashboardScrollRef"
        data-testid="analysis-workspace-scroll"
        class="min-h-0 min-w-0 flex-1 touch-pan-y overflow-y-auto pb-4 pl-4"
      >
        <div
          v-if="marketReviewNotice"
          class="mb-3"
        >
          <Alert
            :variant="marketReviewNotice.variant === 'destructive' ? 'destructive' : 'default'"
            :class="marketReviewNotice.variant === 'success' && 'border-success/30 text-success'"
          >
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
          <Card
            v-for="index in 4"
            :key="index"
          >
            <CardContent class="space-y-3 p-6">
              <Skeleton class="h-5 w-1/3" /><Skeleton class="h-4 w-full" /><Skeleton class="h-4 w-5/6" /><Skeleton class="h-32 w-full" />
            </CardContent>
          </Card>
        </div>
        <div
          v-else-if="selectedReport"
          class="space-y-4 pb-8"
        >
          <Card class="py-0">
            <CardContent class="flex flex-wrap items-center justify-end gap-2 p-3">
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
                @click="handleAskFollowUp"
              >
                <MessageCircle />
                追问 AI
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
            </CardContent>
          </Card>
          <ReportSummary
            :data="selectedReport"
            is-history
          />
        </div>
        <div
          v-else
          class="flex h-full items-center justify-center"
        >
          <Empty class="max-w-xl">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BarChart3 />
              </EmptyMedia><EmptyTitle>开始分析</EmptyTitle><EmptyDescription>输入股票代码进行分析，或从历史记录选择报告查看。</EmptyDescription>
            </EmptyHeader>
          </Empty>
        </div>
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
