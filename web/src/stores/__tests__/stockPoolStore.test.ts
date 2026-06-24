import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi, DuplicateTaskError } from '../../api/analysis';
import { historyApi } from '../../api/history';
import { useStockPoolStore } from '../stockPoolStore';

vi.mock('../../api/history', () => ({
  historyApi: {
    getList: vi.fn(),
    getDetail: vi.fn(),
    deleteRecords: vi.fn(),
  },
}));

vi.mock('../../api/analysis', async () => {
  const actual = await vi.importActual<typeof import('../../api/analysis')>('../../api/analysis');
  return {
    ...actual,
    analysisApi: {
      analyzeAsync: vi.fn(),
    },
  };
});

const historyItem = {
  id: 1,
  queryId: 'q-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  sentimentScore: 82,
  operationAdvice: '买入',
  createdAt: '2026-03-18T08:00:00Z',
};

const historyReport = {
  meta: {
    id: 1,
    queryId: 'q-1',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed' as const,
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '趋势维持强势',
    operationAdvice: '继续观察买点',
    trendPrediction: '短线震荡偏强',
    sentimentScore: 78,
  },
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('stockPoolStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStockPoolStore.getState().resetDashboardState();
  });

  it('loads initial history and auto-selects the first report', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 10,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);

    await useStockPoolStore.getState().loadInitialHistory();

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(1);
    expect(state.historyTotal).toBe(1);
    expect(state.selectedReport?.meta.stockCode).toBe('600519');
    expect(state.isLoadingHistory).toBe(false);
    expect(state.isLoadingReport).toBe(false);
  });

  it('loads a specific history page', async () => {
    const pageTwoItem = {
      ...historyItem,
      id: 11,
      queryId: 'q-11',
      stockCode: 'AAPL',
      stockName: 'Apple',
    };

    useStockPoolStore.setState({
      historyItems: [historyItem],
      currentPage: 1,
      historyTotal: 11,
    });

    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 11,
      page: 2,
      limit: 10,
      items: [pageTwoItem],
    });

    await useStockPoolStore.getState().goToHistoryPage(2);

    const state = useStockPoolStore.getState();
    expect(state.currentPage).toBe(2);
    expect(state.historyItems).toEqual([pageTwoItem]);
    expect(historyApi.getList).toHaveBeenCalledWith(expect.objectContaining({ page: 2, limit: 10 }));
  });

  it('surfaces duplicate task errors without replacing the dashboard error state', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockRejectedValue(
      new DuplicateTaskError('600519', 'task-1', '股票 600519 正在分析中'),
    );

    useStockPoolStore.getState().setQuery('600519');
    await useStockPoolStore.getState().submitAnalysis();

    const state = useStockPoolStore.getState();
    expect(state.duplicateError).toContain('600519');
    expect(state.error).toBeNull();
    expect(state.isAnalyzing).toBe(false);
  });

  it('rejects obviously invalid mixed alphanumeric input before calling the API', async () => {
    useStockPoolStore.getState().setQuery('00aaaaa');

    await useStockPoolStore.getState().submitAnalysis();

    const state = useStockPoolStore.getState();
    expect(state.inputError).toBe('请输入有效的股票代码或股票名称');
    expect(state.isAnalyzing).toBe(false);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
  });

  it('accepts HK suffix codes from autocomplete without local validation errors', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-hk-1',
      stockCode: '00700.HK',
      status: 'pending',
      message: 'accepted',
    } as never);

    await useStockPoolStore.getState().submitAnalysis({
      stockCode: '00700.HK',
      stockName: '腾讯控股',
      originalQuery: '00700',
      selectionSource: 'autocomplete',
    });

    const state = useStockPoolStore.getState();
    expect(state.inputError).toBeUndefined();
    expect(state.isAnalyzing).toBe(false);
    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '00700.HK',
      reportType: 'detailed',
      stockName: '腾讯控股',
      originalQuery: '00700',
      selectionSource: 'autocomplete',
    }));
  });

  it('refreshes the current history page during silent refresh', async () => {
    useStockPoolStore.setState({
      historyItems: [historyItem],
      currentPage: 1,
      historyTotal: 2,
    });

    const refreshedItem = {
      ...historyItem,
      id: 2,
      queryId: 'q-2',
      stockCode: 'AAPL',
      stockName: 'Apple',
    };

    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 2,
      page: 1,
      limit: 10,
      items: [refreshedItem, historyItem],
    });

    await useStockPoolStore.getState().refreshHistory(true);

    const state = useStockPoolStore.getState();
    expect(state.historyItems.map((item) => item.id)).toEqual([2, 1]);
    expect(state.currentPage).toBe(1);
    expect(state.historyTotal).toBe(2);
  });

  it('ignores late history responses after dashboard reset', async () => {
    const deferred = createDeferred<{
      total: number;
      page: number;
      limit: number;
      items: typeof historyItem[];
    }>();

    vi.mocked(historyApi.getList).mockImplementation(() => deferred.promise);

    const loadPromise = useStockPoolStore.getState().loadInitialHistory();
    useStockPoolStore.getState().resetDashboardState();

    deferred.resolve({
      total: 1,
      page: 1,
      limit: 10,
      items: [historyItem],
    });

    await loadPromise;

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(0);
    expect(state.isLoadingHistory).toBe(false);
    expect(state.currentPage).toBe(1);
  });

  it('resets dashboard state', () => {
    useStockPoolStore.setState({
      query: 'AAPL',
      selectedReport: historyReport,
      markdownDrawerOpen: true,
      currentPage: 2,
      historyTotal: 12,
    });

    useStockPoolStore.getState().resetDashboardState();
    const state = useStockPoolStore.getState();
    expect(state.query).toBe('');
    expect(state.selectedReport).toBeNull();
    expect(state.markdownDrawerOpen).toBe(false);
    expect(state.currentPage).toBe(1);
    expect(state.historyTotal).toBe(0);
  });

  it('triggers an analysis with the forceRefresh flag', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-force-1',
      status: 'pending',
    } as never);

    await useStockPoolStore.getState().submitAnalysis({
      stockCode: '600519',
      forceRefresh: true,
    });

    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '600519',
      forceRefresh: true,
    }));
  });
});
