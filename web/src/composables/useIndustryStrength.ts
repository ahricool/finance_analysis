import { tasksApi } from '@/api/tasks';
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue';
import {
  industryStrengthApi as api,
  type Constituents,
  type IndustryPreview,
  type IndustryDetail,
  type IndustryHistory,
  type IndustryRanking,
  type IndustrySnapshot,
} from '@/api/industryStrength';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { computeSummary, historicalMembersUnavailable } from '@/components/industry-strength/display';

export function detailMatchesQuery(
  detail: IndustryDetail | null | undefined,
  code: string,
  tradeDate: string | null | undefined,
): boolean {
  if (!detail || !code || !tradeDate) return false;
  return detail.current.industryCode === code && detail.current.tradeDate === tradeDate;
}

export function useIndustryStrength() {
  const previewMode = ref(false);
  const preview = shallowRef<IndustryPreview | null>(null);
  const taskStatus = ref('');
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let activeTask = '';
  let disposed = false;
  let cacheTimer: ReturnType<typeof setTimeout> | undefined;
  const ranking = shallowRef<IndustryRanking | null>(null);
  const history = shallowRef<IndustryHistory>({ dates: [], items: [] });
  const historyEndTradeDate = ref<string | null>(null);
  const detail = shallowRef<IndustryDetail | null>(null);
  const constituents = shallowRef<Constituents | null>(null);
  const dates = ref<string[]>([]);
  const requestedDate = ref('');
  const selected = ref('');
  const selectedLabel = ref('');
  const dialogOpen = ref(false);
  const missingSelected = ref(false);
  const loading = ref(true);
  const refreshing = ref(false);
  const dateSwitching = ref(false);
  const historyLoading = ref(false);
  const detailLoading = ref(false);
  const membersLoading = ref(false);
  const stale = ref(false);
  const pendingDate = ref('');
  const error = shallowRef<ParsedApiError | null>(null);
  const refreshError = shallowRef<ParsedApiError | null>(null);
  const dateError = shallowRef<ParsedApiError | null>(null);
  const historyError = shallowRef<ParsedApiError | null>(null);
  const datesError = shallowRef<ParsedApiError | null>(null);
  const detailError = shallowRef<ParsedApiError | null>(null);
  const membersError = shallowRef<ParsedApiError | null>(null);

  let rankingSeq = 0;
  let historySeq = 0;
  let detailSeq = 0;
  let membersSeq = 0;
  const constituentsCache = new Map<string, Constituents>();

  const rows = computed(() => ranking.value?.items ?? []);
  const summary = computed(() => computeSummary(rows.value));
  const snapshotMeta = computed(() => rows.value[0] ?? null);
  const actualTradeDate = computed(() => ranking.value?.tradeDate ?? null);
  const latestMode = computed(() => requestedDate.value === '');
  const staleLatest = computed(() => (
    latestMode.value
    && Boolean(ranking.value?.tradeDate)
    && ranking.value?.tradeDate !== ranking.value?.expectedTradeDate
  ));
  const historyMembersUnavailable = computed(() => historicalMembersUnavailable(rows.value));
  const selectedRow = computed(() => rows.value.find((row) => row.industryCode === selected.value) ?? null);
  const matchedDetail = computed(() => (
    detailMatchesQuery(detail.value, selected.value, ranking.value?.tradeDate) ? detail.value : null
  ));
  const chartHistory = computed<IndustryHistory>(() => {
    if (!ranking.value?.tradeDate || historyEndTradeDate.value !== ranking.value.tradeDate) {
      return { dates: [], items: [] };
    }
    return history.value;
  });

  function dropMismatchedDetail(code: string, tradeDate: string | null | undefined) {
    if (!detailMatchesQuery(detail.value, code, tradeDate)) detail.value = null;
  }

  function invalidateConstituents() {
    membersSeq += 1;
    constituentsCache.clear();
    constituents.value = null;
    membersLoading.value = false;
  }

  function invalidateHistory() {
    historySeq += 1;
    historyLoading.value = false;
  }

  async function loadDates() {
    try {
      dates.value = await api.dates();
      datesError.value = null;
    } catch (cause) {
      datesError.value = getParsedApiError(cause);
    }
  }

  async function loadHistory(tradeDate: string, mode: 'replace' | 'refresh' = 'replace') {
    const token = ++historySeq;
    historyLoading.value = true;
    historyError.value = null;
    try {
      const result = await api.history(previewMode.value ? undefined : tradeDate);
      if (token !== historySeq) return;
      history.value = result;
      historyEndTradeDate.value = tradeDate;
    } catch (cause) {
      if (token !== historySeq) return;
      historyError.value = getParsedApiError(cause);
      if (mode === 'refresh' && historyEndTradeDate.value === tradeDate) return;
      history.value = { dates: [], items: [] };
      historyEndTradeDate.value = tradeDate;
    } finally {
      if (token === historySeq) historyLoading.value = false;
    }
  }

  async function loadDetail(code: string) {
    const tradeDate = ranking.value?.tradeDate ?? null;
    const token = ++detailSeq;
    detailLoading.value = true;
    detailError.value = null;
    dropMismatchedDetail(code, tradeDate);
    if (previewMode.value && !rows.value.some(row => row.industryCode === code)) {
      detail.value = null;
      missingSelected.value = true;
      detailLoading.value = false;
      return;
    }
    try {
      const result = await api.detail(code, previewMode.value ? undefined : tradeDate ?? undefined);
      const current = previewMode.value ? rows.value.find(r => r.industryCode === code) : null;
      const data = current ? { current, history: result.history } : result;
      if (token !== detailSeq) return;
      if (!detailMatchesQuery(data, code, tradeDate)) return;
      detail.value = data;
      missingSelected.value = false;
    } catch (cause) {
      if (token !== detailSeq) return;
      detailError.value = getParsedApiError(cause);
      dropMismatchedDetail(code, tradeDate);
    } finally {
      if (token === detailSeq) detailLoading.value = false;
    }
  }

  async function loadConstituents(code: string, force = false) {
    if (previewMode.value) {
      constituents.value = preview.value?.result?.constituents[code] ?? null;
      membersError.value = null;
      membersLoading.value = false;
      return;
    }
    const token = ++membersSeq;
    if (constituents.value?.industryCode !== code) constituents.value = null;
    membersError.value = null;
    if (!force) {
      const cached = constituentsCache.get(code);
      if (cached) {
        if (token !== membersSeq) return;
        constituents.value = cached;
        membersLoading.value = false;
        return;
      }
    }
    membersLoading.value = true;
    try {
      const data = await api.constituents(code);
      if (token !== membersSeq) return;
      constituentsCache.set(code, data);
      constituents.value = data;
    } catch (cause) {
      if (token !== membersSeq) return;
      membersError.value = getParsedApiError(cause);
    } finally {
      if (token === membersSeq) membersLoading.value = false;
    }
  }

  function syncSelection(items: IndustrySnapshot[], reloadMembers: boolean) {
    if (!dialogOpen.value || !selected.value) return;
    const exists = items.some((row) => row.industryCode === selected.value);
    if (exists) {
      missingSelected.value = false;
      void loadDetail(selected.value);
      if (reloadMembers) void loadConstituents(selected.value, true);
      return;
    }
    missingSelected.value = true;
    detail.value = null;
    detailSeq += 1;
    detailLoading.value = false;
  }

  async function loadRanking(kind: 'initial' | 'refresh' | 'date') {
    const token = ++rankingSeq;
    if (kind === 'initial') {
      loading.value = true;
      error.value = null;
    } else if (kind === 'refresh') {
      refreshing.value = true;
      refreshError.value = null;
    } else {
      dateSwitching.value = true;
      dateError.value = null;
      pendingDate.value = requestedDate.value;
    }

    void loadDates();

    try {
      let data: IndustryRanking;
      if (previewMode.value) {
        const result = await api.preview();
        if (token !== rankingSeq) return;
        preview.value = result;
        taskStatus.value = result.status;
        clearTimeout(cacheTimer);
        if (result.status === 'processing' && !activeTask) {
          cacheTimer = setTimeout(() => { if (!disposed && previewMode.value) void loadRanking('refresh'); }, 3000);
        }
        data = result.result ?? { tradeDate: null, expectedTradeDate: '', source: '盘中预览', items: [] };
      } else {
        data = await api.ranking(requestedDate.value || undefined);
      }
      if (token !== rankingSeq) return;
      ranking.value = data;
      stale.value = false;
      pendingDate.value = '';
      refreshError.value = null;
      dateError.value = null;
      if (kind === 'refresh') invalidateConstituents();
      if (data.items.length && data.tradeDate) {
        const sameDate = historyEndTradeDate.value === data.tradeDate;
        const historyMode = kind === 'refresh' && sameDate ? 'refresh' : 'replace';
        if (!sameDate) invalidateHistory();
        void loadHistory(data.tradeDate, historyMode);
      } else {
        invalidateHistory();
        historyError.value = null;
        history.value = { dates: [], items: [] };
        historyEndTradeDate.value = data.tradeDate;
      }
      syncSelection(data.items, kind === 'refresh');
    } catch (cause) {
      if (token !== rankingSeq) return;
      const parsed = getParsedApiError(cause);
      if (kind === 'refresh' && ranking.value) {
        refreshError.value = parsed;
        stale.value = true;
      } else if (kind === 'date' && ranking.value) {
        dateError.value = parsed;
      } else {
        error.value = parsed;
        ranking.value = null;
      }
    } finally {
      if (token === rankingSeq) {
        loading.value = false;
        refreshing.value = false;
        dateSwitching.value = false;
      }
    }
  }

  async function switchMode() {
    clearTimeout(cacheTimer);
    previewMode.value = !previewMode.value;
    preview.value = null;
    rankingSeq += 1;
    detailSeq += 1;
    invalidateConstituents();
    invalidateHistory();
    detail.value = null;
    ranking.value = null;
    history.value = { dates: [], items: [] };
    setDialogOpen(false);
    await loadRanking('initial');
  }

  async function pollTask() {
    try {
      const task = await tasksApi.getTaskRunDetail(activeTask);
      if (disposed) return;
      taskStatus.value = task.status;
      if (['pending', 'processing', 'retrying'].includes(task.status)) {
        pollTimer = setTimeout(() => { void pollTask(); }, 2000);
        return;
      }
      activeTask = '';
      if (previewMode.value) await loadRanking('refresh');
      taskStatus.value = task.status;
      if (task.status === 'failed') refreshError.value = getParsedApiError(new Error(task.error || '预览任务失败'));
    } catch (cause) {
      refreshError.value = getParsedApiError(cause);
      activeTask = '';
    } finally {
      if (!activeTask) refreshing.value = false;
    }
  }

  async function refresh() {
    if (activeTask) return;
    if (!previewMode.value) return loadRanking('refresh');
    refreshing.value = true;
    refreshError.value = null;
    try {
      const task = await api.runPreview();
      activeTask = task.taskId;
      taskStatus.value = 'pending';
      await pollTask();
    } catch (cause) {
      refreshError.value = getParsedApiError(cause);
      refreshing.value = false;
    }
  }

  function openIndustry(code: string) {
    selected.value = code;
    selectedLabel.value = rows.value.find((row) => row.industryCode === code)?.industryName ?? code;
    dialogOpen.value = true;
    missingSelected.value = false;
    dropMismatchedDetail(code, ranking.value?.tradeDate);
    void loadDetail(code);
    void loadConstituents(code);
  }

  function setDialogOpen(open: boolean) {
    dialogOpen.value = open;
    if (!open) {
      detailSeq += 1;
      membersSeq += 1;
      detailLoading.value = false;
      membersLoading.value = false;
    }
  }

  function retryRanking() {
    void loadRanking(ranking.value ? (pendingDate.value ? 'date' : 'refresh') : 'initial');
  }

  function retryHistory() {
    if (ranking.value?.tradeDate) void loadHistory(ranking.value.tradeDate);
  }

  function retryDetail() {
    if (selected.value) void loadDetail(selected.value);
  }

  function retryConstituents() {
    if (selected.value) void loadConstituents(selected.value, true);
  }

  function goLatest() {
    requestedDate.value = '';
    void loadRanking('date');
  }

  onBeforeUnmount(() => {
    disposed = true;
    clearTimeout(cacheTimer);
    clearTimeout(pollTimer);
    activeTask = '';
    rankingSeq += 1;
    historySeq += 1;
    detailSeq += 1;
    membersSeq += 1;
  });

  return {
    previewMode, preview, taskStatus, switchMode,
    ranking,
    history,
    historyEndTradeDate,
    chartHistory,
    detail,
    matchedDetail,
    constituents,
    dates,
    requestedDate,
    selected,
    selectedLabel,
    dialogOpen,
    missingSelected,
    loading,
    refreshing,
    dateSwitching,
    historyLoading,
    detailLoading,
    membersLoading,
    stale,
    pendingDate,
    error,
    refreshError,
    dateError,
    historyError,
    datesError,
    detailError,
    membersError,
    rows,
    summary,
    snapshotMeta,
    actualTradeDate,
    latestMode,
    staleLatest,
    historyMembersUnavailable,
    selectedRow,
    loadRanking,
    openIndustry,
    setDialogOpen,
    retryRanking,
    retryHistory,
    retryDetail,
    retryConstituents,
    retryDates: loadDates,
    goLatest,
    changeDate: (value: string) => {
      requestedDate.value = value;
      void loadRanking('date');
    },
    refresh,
  };
}
