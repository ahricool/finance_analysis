<script setup lang="ts">
import { analysisApi } from '@/api/analysis';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import HistoryList from '@/components/history/HistoryList.vue';
import ReportMarkdown from '@/components/report/ReportMarkdown.vue';
import ReportSummary from '@/components/report/ReportSummary.vue';
import { useDashboardLifecycle } from '@/composables/useDashboardLifecycle';
import { useHomeDashboardState } from '@/composables/useHomeDashboardState';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { BarChart3 } from 'lucide-vue-next';
import { computed, ref, unref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useRouter } from 'vue-router';

type MarketReviewNotice = {
  variant: 'success' | 'warning' | 'danger';
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

const reportLanguage = computed(() => normalizeReportLanguage(selectedReport.value?.meta.reportLanguage));
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
    data-testid="home-dashboard"
    class="flex h-[calc(100vh-5rem)] w-full flex-col overflow-hidden sm:h-[calc(100vh-5.5rem)] md:flex-row lg:h-[calc(100vh-6rem)]"
  >
    <div class="mx-auto flex w-full max-w-full min-w-0 flex-1 flex-col">
      <header class="flex min-w-0 flex-shrink-0 items-center overflow-hidden px-3 py-3 md:px-4 md:py-4">
        <div class="flex min-w-0 flex-1 flex-col gap-2.5 md:flex-row md:items-center">
          <div class="flex min-w-0 flex-1 items-center gap-2.5">
            <button
              type="button"
              class="-ml-1 flex-shrink-0 rounded-lg p-1.5 text-secondary-text transition-colors hover:bg-hover hover:text-foreground md:hidden"
              aria-label="历史记录"
              @click="sidebarOpen = true"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div class="relative min-w-0 flex-1">
              <StockAutocomplete
                :model-value="query"
                :disabled="isAnalyzing"
                placeholder="输入股票代码或名称，如 600519、贵州茅台、AAPL"
                :class="inputError ? 'border-danger/50' : undefined"
                @update:model-value="(v: string) => unref(setQuery)(v)"
                @submit="onStockAutocompleteSubmit"
              />
            </div>
          </div>
          <div class="flex min-w-0 flex-shrink-0 items-center gap-2.5">
            <Button
              type="button"
              variant="secondary"
              size="md"
              :is-loading="isSubmittingMarketReview"
              loading-text="提交中"
              class="h-10 flex-1 whitespace-nowrap md:flex-none"
              @click="handleTriggerMarketReview"
            >
              <BarChart3 class="h-4 w-4" aria-hidden="true" />
              大盘复盘
            </Button>
            <button
              type="button"
              :disabled="!query || isAnalyzing"
              class="btn-primary flex h-10 flex-1 items-center justify-center gap-1.5 whitespace-nowrap md:flex-none"
              @click="handleSubmitAnalysisWrapper()"
            >
              <template v-if="isAnalyzing">
                <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                分析中
              </template>
              <template v-else>分析</template>
            </button>
          </div>
        </div>
      </header>

      <div v-if="inputError || duplicateError" class="px-3 pb-2 md:px-4">
        <InlineAlert
          v-if="inputError"
          variant="danger"
          title="输入有误"
          class="rounded-xl px-3 py-2 text-xs shadow-none"
        >
          {{ inputError }}
        </InlineAlert>
        <InlineAlert
          v-else-if="duplicateError"
          variant="warning"
          title="任务已存在"
          class="rounded-xl px-3 py-2 text-xs shadow-none"
        >
          {{ duplicateError }}
        </InlineAlert>
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

        <div
          v-if="sidebarOpen"
          class="fixed inset-0 z-40 md:hidden"
          @click="sidebarOpen = false"
        >
          <div class="page-drawer-overlay absolute inset-0" />
          <div
            class="dashboard-card absolute bottom-0 left-0 top-0 flex w-72 flex-col overflow-hidden !rounded-none !rounded-r-xl p-3 shadow-2xl"
            @click.stop
          >
            <div class="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
              <HistoryList
                :items="historyItems"
                :is-loading="isLoadingHistory"
                :current-page="currentPage"
                :total-pages="historyTotalPages"
                :total-count="historyTotal"
                :selected-id="selectedReport?.meta.id"
                class="min-h-0 flex-1 overflow-hidden"
                @item-click="handleHistoryItemClick"
                @page-change="handleHistoryPageChange"
              />
            </div>
          </div>
        </div>

        <section
          ref="dashboardScrollRef"
          data-testid="home-dashboard-scroll"
          class="min-h-0 min-w-0 flex-1 touch-pan-y overflow-x-auto overflow-y-auto px-3 pb-4 md:px-6"
        >
          <div v-if="marketReviewNotice" class="mb-3">
            <InlineAlert
              :variant="marketReviewNotice.variant"
              :title="marketReviewNotice.title"
              class="rounded-xl px-3 py-2 text-xs shadow-none"
            >
              {{ marketReviewNotice.message }}
            </InlineAlert>
          </div>

          <div v-if="marketReviewError" class="mb-3">
            <ApiErrorAlert
              :error="marketReviewError"
              class="mb-1"
              @dismiss="marketReviewError = null"
            />
          </div>

          <ApiErrorAlert v-if="error" :error="error" class="mb-3" @dismiss="() => unref(clearError)()" />

          <div v-if="isLoadingReport" class="flex h-full flex-col items-center justify-center">
            <DashboardStateBlock title="加载报告中..." loading />
          </div>
          <div v-else-if="selectedReport" class="space-y-4 pb-8">
            <div class="flex flex-wrap items-center justify-end gap-2">
              <Button
                variant="home-action-ai"
                size="sm"
                :disabled="isAnalyzing || selectedReport.meta.id === undefined"
                @click="handleReanalyze"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                  />
                </svg>
                {{ reportText.reanalyze }}
              </Button>
              <Button
                variant="home-action-ai"
                size="sm"
                :disabled="selectedReport.meta.id === undefined"
                @click="handleAskFollowUp"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
                追问 AI
              </Button>
              <Button
                variant="home-action-ai"
                size="sm"
                :disabled="selectedReport.meta.id === undefined"
                @click="unref(openMarkdownDrawer)()"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
                {{ reportText.fullReport }}
              </Button>
            </div>
            <ReportSummary :data="selectedReport" is-history />
          </div>
          <div v-else class="flex h-full items-center justify-center">
            <EmptyState
              title="开始分析"
              description="输入股票代码进行分析，或从左侧选择历史报告查看。"
              class="max-w-xl border-dashed"
            >
              <template #icon>
                <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  />
                </svg>
              </template>
            </EmptyState>
          </div>
        </section>
      </div>
    </div>

    <ReportMarkdown
      v-if="markdownDrawerOpen && selectedReport?.meta.id"
      :record-id="selectedReport.meta.id"
      :stock-name="selectedReport.meta.stockName || ''"
      :stock-code="selectedReport.meta.stockCode"
      :report-language="reportLanguage"
      @close="() => unref(closeMarkdownDrawer)()"
    />

  </div>
</template>
