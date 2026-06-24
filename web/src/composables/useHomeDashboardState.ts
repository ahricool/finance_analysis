import { computed, unref } from 'vue';
import { useStockPoolStore } from '@/stores/stockPoolStore';

const HISTORY_PAGE_SIZE = 10;

/**
 * Centralizes stock-pool / dashboard selections for the home page (vue-zustand).
 */
export function useHomeDashboardState() {
  const dashboardState = useStockPoolStore((state) => ({
    query: state.query,
    inputError: state.inputError,
    duplicateError: state.duplicateError,
    error: state.error,
    isAnalyzing: state.isAnalyzing,
    historyItems: state.historyItems,
    isLoadingHistory: state.isLoadingHistory,
    currentPage: state.currentPage,
    historyTotal: state.historyTotal,
    selectedReport: state.selectedReport,
    isLoadingReport: state.isLoadingReport,
    markdownDrawerOpen: state.markdownDrawerOpen,
    setQuery: state.setQuery,
    clearError: state.clearError,
    loadInitialHistory: state.loadInitialHistory,
    refreshHistory: state.refreshHistory,
    goToHistoryPage: state.goToHistoryPage,
    selectHistoryItem: state.selectHistoryItem,
    submitAnalysis: state.submitAnalysis,
    openMarkdownDrawer: state.openMarkdownDrawer,
    closeMarkdownDrawer: state.closeMarkdownDrawer,
  }));

  const historyTotalPages = computed(() =>
    Math.max(1, Math.ceil(unref(dashboardState.historyTotal) / HISTORY_PAGE_SIZE)),
  );

  return {
    ...dashboardState,
    historyTotalPages,
  };
}
