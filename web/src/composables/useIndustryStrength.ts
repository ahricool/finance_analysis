import { computed, onBeforeUnmount, ref, shallowRef } from 'vue';
import {
  industryStrengthApi as api,
  type Constituents,
  type IndustryDetail,
  type IndustryHistory,
  type IndustryRanking,
  type IndustrySnapshot,
} from '@/api/industryStrength';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { computeSummary, historicalMembersUnavailable } from '@/components/industry-strength/display';

export type IndustryView = 'ranking' | 'matrix' | 'history';
export type DetailTab = 'overview' | 'history' | 'constituents';

export function useIndustryStrength() {
  const ranking = shallowRef<IndustryRanking | null>(null);
  const history = shallowRef<IndustryHistory>({ dates: [], items: [] });
  const detail = shallowRef<IndustryDetail | null>(null);
  const constituents = shallowRef<Constituents | null>(null);
  const dates = ref<string[]>([]);
  const requestedDate = ref('');
  const selected = ref('');
  const selectedLabel = ref('');
  const drawerOpen = ref(false);
  const missingSelected = ref(false);
  const view = ref<IndustryView>('ranking');
  const detailTab = ref<DetailTab>('overview');
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

  function invalidateConstituents() {
    constituentsCache.clear();
    constituents.value = null;
  }

  async function loadDates() {
    try {
      dates.value = await api.dates();
      datesError.value = null;
    } catch (cause) {
      datesError.value = getParsedApiError(cause);
    }
  }

  async function loadHistory(tradeDate: string) {
    const token = ++historySeq;
    historyLoading.value = true;
    historyError.value = null;
    try {
      const result = await api.history(tradeDate);
      if (token !== historySeq) return;
      history.value = result;
    } catch (cause) {
      if (token !== historySeq) return;
      historyError.value = getParsedApiError(cause);
    } finally {
      if (token === historySeq) historyLoading.value = false;
    }
  }

  async function loadDetail(code: string) {
    const token = ++detailSeq;
    detailLoading.value = true;
    detailError.value = null;
    try {
      const data = await api.detail(code, ranking.value?.tradeDate ?? undefined);
      if (token !== detailSeq) return;
      detail.value = data;
      missingSelected.value = false;
    } catch (cause) {
      if (token !== detailSeq) return;
      detailError.value = getParsedApiError(cause);
      if (detail.value?.current.industryCode !== code) detail.value = null;
    } finally {
      if (token === detailSeq) detailLoading.value = false;
    }
  }

  async function loadConstituents(code: string, force = false) {
    const token = ++membersSeq;
    membersError.value = null;
    if (!force) {
      const cached = constituentsCache.get(code);
      if (cached) {
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
    if (!drawerOpen.value || !selected.value) return;
    const exists = items.some((row) => row.industryCode === selected.value);
    if (exists) {
      missingSelected.value = false;
      void loadDetail(selected.value);
      if (detailTab.value === 'constituents') void loadConstituents(selected.value, reloadMembers);
      return;
    }
    missingSelected.value = true;
    detail.value = null;
    ++detailSeq;
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
      const data = await api.ranking(requestedDate.value || undefined);
      if (token !== rankingSeq) return;
      ranking.value = data;
      stale.value = false;
      pendingDate.value = '';
      refreshError.value = null;
      dateError.value = null;
      if (kind === 'refresh') invalidateConstituents();
      if (data.items.length && data.tradeDate) void loadHistory(data.tradeDate);
      else history.value = { dates: [], items: [] };
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

  function openIndustry(code: string) {
    selected.value = code;
    selectedLabel.value = rows.value.find((row) => row.industryCode === code)?.industryName ?? code;
    drawerOpen.value = true;
    missingSelected.value = false;
    void loadDetail(code);
    if (detailTab.value === 'constituents') void loadConstituents(code);
  }

  function setDrawerOpen(open: boolean) {
    drawerOpen.value = open;
    if (!open) {
      ++detailSeq;
      ++membersSeq;
      detailLoading.value = false;
      membersLoading.value = false;
    }
  }

  function setDetailTab(tab: DetailTab) {
    detailTab.value = tab;
    if (tab === 'constituents' && selected.value) void loadConstituents(selected.value);
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
    rankingSeq += 1;
    historySeq += 1;
    detailSeq += 1;
    membersSeq += 1;
  });

  return {
    ranking,
    history,
    detail,
    constituents,
    dates,
    requestedDate,
    selected,
    selectedLabel,
    drawerOpen,
    missingSelected,
    view,
    detailTab,
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
    setDrawerOpen,
    setDetailTab,
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
    refresh: () => loadRanking('refresh'),
  };
}
