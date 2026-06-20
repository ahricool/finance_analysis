import { computed, unref } from 'vue';
import { useStockPoolStore } from '@/stores/stockPoolStore';

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
    selectedHistoryIds: state.selectedHistoryIds,
    isDeletingHistory: state.isDeletingHistory,
    isLoadingHistory: state.isLoadingHistory,
    isLoadingMore: state.isLoadingMore,
    hasMore: state.hasMore,
    selectedReport: state.selectedReport,
    isLoadingReport: state.isLoadingReport,
    markdownDrawerOpen: state.markdownDrawerOpen,
    setQuery: state.setQuery,
    clearError: state.clearError,
    loadInitialHistory: state.loadInitialHistory,
    refreshHistory: state.refreshHistory,
    loadMoreHistory: state.loadMoreHistory,
    selectHistoryItem: state.selectHistoryItem,
    toggleHistorySelection: state.toggleHistorySelection,
    toggleSelectAllVisible: state.toggleSelectAllVisible,
    deleteSelectedHistory: state.deleteSelectedHistory,
    submitAnalysis: state.submitAnalysis,
    openMarkdownDrawer: state.openMarkdownDrawer,
    closeMarkdownDrawer: state.closeMarkdownDrawer,
  }));

  const selectedIds = computed(() => new Set(unref(dashboardState.selectedHistoryIds)));

  return {
    ...dashboardState,
    selectedIds,
  };
}
