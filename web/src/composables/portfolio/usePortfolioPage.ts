import {
  computed,
  onMounted,
  ref,
  shallowRef,
  watch,
} from 'vue';
import { portfolioApi } from '@/api/portfolio';
import type { ParsedApiError } from '@/api/error';
import { getParsedApiError } from '@/api/error';
import type {
  PortfolioAccountItem,
  PortfolioCashDirection,
  PortfolioCashLedgerListItem,
  PortfolioCorporateActionListItem,
  PortfolioCorporateActionType,
  PortfolioCostMethod,
  PortfolioImportBrokerItem,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioRiskResponse,
  PortfolioSide,
  PortfolioSnapshotResponse,
  PortfolioTradeListItem,
} from '@/types/portfolio';
import {
  buildFxRefreshFeedback,
  DEFAULT_PAGE_SIZE,
  FALLBACK_BROKERS,
  formatBrokerLabel,
  formatCashDirectionLabel,
  formatCorporateActionLabel,
  formatMoney,
  formatPct,
  formatPositionMoney,
  formatPositionPrice,
  formatSideLabel,
  formatSignedPct,
  getCsvCommitVariant,
  getCsvParseVariant,
  getFxRefreshFeedbackVariant,
  getPositionPriceLabel,
  getTodayIso,
  hasPositionPrice,
  PIE_COLORS,
  type AccountOption,
  type EventType,
  type FlatPosition,
  type FxRefreshContext,
  type FxRefreshFeedback,
  type PendingDelete,
} from './portfolioHelpers';

export function usePortfolioPage() {
  const accounts = ref<PortfolioAccountItem[]>([]);
  const selectedAccount = ref<AccountOption>('all');
  const showCreateAccount = ref(false);
  const accountCreating = ref(false);
  const accountCreateError = ref<string | null>(null);
  const accountCreateSuccess = ref<string | null>(null);
  const accountForm = ref({
    name: '',
    broker: 'Demo',
    market: 'cn' as 'cn' | 'hk' | 'us',
    baseCurrency: 'CNY',
  });
  const costMethod = ref<PortfolioCostMethod>('fifo');
  const snapshot = shallowRef<PortfolioSnapshotResponse | null>(null);
  const risk = shallowRef<PortfolioRiskResponse | null>(null);
  const isLoading = ref(false);
  const fxRefreshing = ref(false);
  const fxRefreshFeedback = shallowRef<FxRefreshFeedback | null>(null);
  const error = shallowRef<ParsedApiError | null>(null);
  const riskWarning = ref<string | null>(null);
  const writeWarning = ref<string | null>(null);

  const brokers = ref<PortfolioImportBrokerItem[]>([]);
  const selectedBroker = ref('huatai');
  const csvFile = shallowRef<File | null>(null);
  const csvDryRun = ref(true);
  const csvParsing = ref(false);
  const csvCommitting = ref(false);
  const csvParseResult = shallowRef<PortfolioImportParseResponse | null>(null);
  const csvCommitResult = shallowRef<PortfolioImportCommitResponse | null>(null);
  const brokerLoadWarning = ref<string | null>(null);

  const eventType = ref<EventType>('trade');
  const eventDateFrom = ref('');
  const eventDateTo = ref('');
  const eventSymbol = ref('');
  const eventSide = ref<'' | PortfolioSide>('');
  const eventDirection = ref<'' | PortfolioCashDirection>('');
  const eventActionType = ref<'' | PortfolioCorporateActionType>('');
  const eventPage = ref(1);
  const eventTotal = ref(0);
  const eventLoading = ref(false);
  const tradeEvents = ref<PortfolioTradeListItem[]>([]);
  const cashEvents = ref<PortfolioCashLedgerListItem[]>([]);
  const corporateEvents = ref<PortfolioCorporateActionListItem[]>([]);
  const pendingDelete = shallowRef<PendingDelete | null>(null);
  const deleteLoading = ref(false);

  const tradeForm = ref({
    symbol: '',
    tradeDate: getTodayIso(),
    side: 'buy' as PortfolioSide,
    quantity: '',
    price: '',
    fee: '',
    tax: '',
    tradeUid: '',
    note: '',
  });
  const cashForm = ref({
    eventDate: getTodayIso(),
    direction: 'in' as PortfolioCashDirection,
    amount: '',
    currency: '',
    note: '',
  });
  const corpForm = ref({
    symbol: '',
    effectiveDate: getTodayIso(),
    actionType: 'cash_dividend' as PortfolioCorporateActionType,
    cashDividendPerShare: '',
    splitRatio: '',
    note: '',
  });

  const queryAccountId = computed(() =>
    selectedAccount.value === 'all' ? undefined : selectedAccount.value,
  );

  const selectedAccountModel = computed<string>({
    get: () => String(selectedAccount.value),
    set: (v) => {
      selectedAccount.value = v === 'all' ? 'all' : Number(v);
    },
  });

  const refreshViewKey = computed(
    () =>
      `${selectedAccount.value === 'all' ? 'all' : `account:${selectedAccount.value}`}:cost:${costMethod.value}`,
  );

  const refreshContext = shallowRef<FxRefreshContext>({ viewKey: '', requestId: 0 });

  const hasAccounts = computed(() => accounts.value.length > 0);

  const writableAccount = computed(() =>
    selectedAccount.value === 'all'
      ? undefined
      : accounts.value.find((item) => item.id === selectedAccount.value),
  );

  const writableAccountId = computed(() => writableAccount.value?.id);

  const writeBlocked = computed(() => !writableAccountId.value);

  const totalEventPages = computed(() => Math.max(1, Math.ceil(eventTotal.value / DEFAULT_PAGE_SIZE)));

  const currentEventCount = computed(() => {
    if (eventType.value === 'trade') return tradeEvents.value.length;
    if (eventType.value === 'cash') return cashEvents.value.length;
    return corporateEvents.value.length;
  });

  const positionRows = computed<FlatPosition[]>(() => {
    const snap = snapshot.value;
    if (!snap) return [];
    const rows: FlatPosition[] = [];
    for (const account of snap.accounts || []) {
      for (const position of account.positions || []) {
        rows.push({
          ...position,
          accountId: account.accountId,
          accountName: account.accountName,
        });
      }
    }
    rows.sort((a, b) => Number(b.marketValueBase || 0) - Number(a.marketValueBase || 0));
    return rows;
  });

  const sectorPieData = computed(() => {
    const sectors = risk.value?.sectorConcentration?.topSectors || [];
    return sectors
      .slice(0, 6)
      .map((item) => ({
        name: item.sector,
        value: Number(item.weightPct || 0),
      }))
      .filter((item) => item.value > 0);
  });

  const positionFallbackPieData = computed(() => {
    if (!risk.value?.concentration?.topPositions?.length) {
      return [];
    }
    return risk.value.concentration.topPositions
      .slice(0, 6)
      .map((item) => ({
        name: item.symbol,
        value: Number(item.weightPct || 0),
      }))
      .filter((item) => item.value > 0);
  });

  const concentrationPieData = computed(() =>
    sectorPieData.value.length > 0 ? sectorPieData.value : positionFallbackPieData.value,
  );

  const concentrationMode = computed(() => (sectorPieData.value.length > 0 ? 'sector' : 'position'));

  const concentrationPieChartOption = computed(() => {
    const data = concentrationPieData.value.map((item, index) => ({
      name: item.name,
      value: item.value,
      itemStyle: {
        color: PIE_COLORS[index % PIE_COLORS.length],
      },
    }));
    return {
      tooltip: {
        trigger: 'item' as const,
        formatter: (params: { name: string; value: number }) =>
          `${params.name}: ${Number(params.value).toFixed(2)}%`,
      },
      legend: {
        bottom: 0,
        left: 'center' as const,
      },
      series: [
        {
          type: 'pie' as const,
          radius: '90%',
          center: ['50%', '45%'] as [string, string],
          data,
          label: { show: false },
        },
      ],
    };
  });

  function isActiveRefreshContext(requestedViewKey: string, requestedRequestId: number): boolean {
    return (
      refreshContext.value.viewKey === requestedViewKey
      && refreshContext.value.requestId === requestedRequestId
    );
  }

  async function loadAccounts(): Promise<void> {
    try {
      const response = await portfolioApi.getAccounts(false);
      const items = response.accounts || [];
      accounts.value = items;

      const prev = selectedAccount.value;
      if (items.length === 0) {
        selectedAccount.value = 'all';
      } else if (prev !== 'all' && !items.some((item) => item.id === prev)) {
        selectedAccount.value = items[0].id;
      }

      if (items.length === 0) showCreateAccount.value = true;
    } catch (err) {
      error.value = getParsedApiError(err);
    }
  }

  async function loadBrokers(): Promise<void> {
    const brokerSelection = selectedBroker.value;
    try {
      const response = await portfolioApi.listImportBrokers();
      const brokerItems = response.brokers || [];
      if (brokerItems.length === 0) {
        brokers.value = FALLBACK_BROKERS;
        brokerLoadWarning.value =
          '券商列表接口返回为空，已回退为内置券商列表（华泰/中信/招商）。';
        if (!FALLBACK_BROKERS.some((item) => item.broker === brokerSelection)) {
          selectedBroker.value = FALLBACK_BROKERS[0].broker;
        }
        return;
      }
      brokers.value = brokerItems;
      brokerLoadWarning.value = null;
      if (!brokerItems.some((item) => item.broker === brokerSelection)) {
        selectedBroker.value = brokerItems[0].broker;
      }
    } catch {
      brokers.value = FALLBACK_BROKERS;
      brokerLoadWarning.value = '券商列表接口不可用，已回退为内置券商列表（华泰/中信/招商）。';
      if (!FALLBACK_BROKERS.some((item) => item.broker === brokerSelection)) {
        selectedBroker.value = FALLBACK_BROKERS[0].broker;
      }
    }
  }

  async function loadSnapshotAndRisk(): Promise<void> {
    isLoading.value = true;
    riskWarning.value = null;
    try {
      const snapshotData = await portfolioApi.getSnapshot({
        accountId: queryAccountId.value,
        costMethod: costMethod.value,
      });
      snapshot.value = snapshotData;
      error.value = null;

      try {
        const riskData = await portfolioApi.getRisk({
          accountId: queryAccountId.value,
          costMethod: costMethod.value,
        });
        risk.value = riskData;
      } catch (riskErr) {
        risk.value = null;
        const parsed = getParsedApiError(riskErr);
        riskWarning.value = parsed.message || '风险数据获取失败，已降级为仅展示快照数据。';
      }
    } catch (err) {
      snapshot.value = null;
      risk.value = null;
      error.value = getParsedApiError(err);
    } finally {
      isLoading.value = false;
    }
  }

  async function loadEventsPage(page: number): Promise<void> {
    eventLoading.value = true;
    try {
      if (eventType.value === 'trade') {
        const response = await portfolioApi.listTrades({
          accountId: queryAccountId.value,
          dateFrom: eventDateFrom.value || undefined,
          dateTo: eventDateTo.value || undefined,
          symbol: eventSymbol.value || undefined,
          side: eventSide.value || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        tradeEvents.value = response.items || [];
        eventTotal.value = response.total || 0;
      } else if (eventType.value === 'cash') {
        const response = await portfolioApi.listCashLedger({
          accountId: queryAccountId.value,
          dateFrom: eventDateFrom.value || undefined,
          dateTo: eventDateTo.value || undefined,
          direction: eventDirection.value || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        cashEvents.value = response.items || [];
        eventTotal.value = response.total || 0;
      } else {
        const response = await portfolioApi.listCorporateActions({
          accountId: queryAccountId.value,
          dateFrom: eventDateFrom.value || undefined,
          dateTo: eventDateTo.value || undefined,
          symbol: eventSymbol.value || undefined,
          actionType: eventActionType.value || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        corporateEvents.value = response.items || [];
        eventTotal.value = response.total || 0;
      }
    } catch (err) {
      error.value = getParsedApiError(err);
    } finally {
      eventLoading.value = false;
    }
  }

  async function loadEvents(): Promise<void> {
    await loadEventsPage(eventPage.value);
  }

  async function refreshPortfolioData(page = eventPage.value): Promise<void> {
    await Promise.all([loadSnapshotAndRisk(), loadEventsPage(page)]);
  }

  async function reloadSnapshotAndRiskForScope(
    requestedViewKey: string,
    requestedRequestId: number,
    requestedAccountId: number | undefined,
    requestedCostMethod: PortfolioCostMethod,
  ): Promise<boolean> {
    if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
      return false;
    }

    riskWarning.value = null;

    try {
      const snapshotData = await portfolioApi.getSnapshot({
        accountId: requestedAccountId,
        costMethod: requestedCostMethod,
      });
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return false;
      }
      snapshot.value = snapshotData;
      error.value = null;

      try {
        const riskData = await portfolioApi.getRisk({
          accountId: requestedAccountId,
          costMethod: requestedCostMethod,
        });
        if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
          return false;
        }
        risk.value = riskData;
        riskWarning.value = null;
      } catch (riskErr) {
        if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
          return false;
        }
        risk.value = null;
        const parsed = getParsedApiError(riskErr);
        riskWarning.value = parsed.message || '风险数据获取失败，已降级为仅展示快照数据。';
      }
      return true;
    } catch (err) {
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return false;
      }
      snapshot.value = null;
      risk.value = null;
      error.value = getParsedApiError(err);
      return false;
    }
  }

  async function handleTradeSubmit(e: Event): Promise<void> {
    e.preventDefault();
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行录入或导入提交。';
      return;
    }
    try {
      writeWarning.value = null;
      const wf = tradeForm.value;
      await portfolioApi.createTrade({
        accountId: writableAccountId.value,
        symbol: wf.symbol,
        tradeDate: wf.tradeDate,
        side: wf.side,
        quantity: Number(wf.quantity),
        price: Number(wf.price),
        fee: Number(wf.fee || 0),
        tax: Number(wf.tax || 0),
        tradeUid: wf.tradeUid || undefined,
        note: wf.note || undefined,
      });
      await refreshPortfolioData();
      tradeForm.value = {
        ...tradeForm.value,
        symbol: '',
        tradeUid: '',
        note: '',
      };
    } catch (err) {
      error.value = getParsedApiError(err);
    }
  }

  async function handleCashSubmit(e: Event): Promise<void> {
    e.preventDefault();
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行录入或导入提交。';
      return;
    }
    try {
      writeWarning.value = null;
      const cf = cashForm.value;
      await portfolioApi.createCashLedger({
        accountId: writableAccountId.value,
        eventDate: cf.eventDate,
        direction: cf.direction,
        amount: Number(cf.amount),
        currency: cf.currency || undefined,
        note: cf.note || undefined,
      });
      await refreshPortfolioData();
      cashForm.value = { ...cashForm.value, note: '' };
    } catch (err) {
      error.value = getParsedApiError(err);
    }
  }

  async function handleCorporateSubmit(e: Event): Promise<void> {
    e.preventDefault();
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行录入或导入提交。';
      return;
    }
    try {
      writeWarning.value = null;
      const f = corpForm.value;
      await portfolioApi.createCorporateAction({
        accountId: writableAccountId.value,
        symbol: f.symbol,
        effectiveDate: f.effectiveDate,
        actionType: f.actionType,
        cashDividendPerShare: f.cashDividendPerShare ? Number(f.cashDividendPerShare) : undefined,
        splitRatio: f.splitRatio ? Number(f.splitRatio) : undefined,
        note: f.note || undefined,
      });
      await refreshPortfolioData();
      corpForm.value = { ...corpForm.value, symbol: '', note: '' };
    } catch (err) {
      error.value = getParsedApiError(err);
    }
  }

  async function handleParseCsv(): Promise<void> {
    const file = csvFile.value;
    if (!file) return;
    try {
      csvParsing.value = true;
      const parsed = await portfolioApi.parseCsvImport(selectedBroker.value, file);
      csvParseResult.value = parsed;
      csvCommitResult.value = null;
    } catch (err) {
      error.value = getParsedApiError(err);
    } finally {
      csvParsing.value = false;
    }
  }

  async function handleCommitCsv(): Promise<void> {
    const file = csvFile.value;
    if (!file) return;
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行录入或导入提交。';
      return;
    }
    try {
      writeWarning.value = null;
      csvCommitting.value = true;
      const committed = await portfolioApi.commitCsvImport(
        writableAccountId.value,
        selectedBroker.value,
        file,
        csvDryRun.value,
      );
      csvCommitResult.value = committed;
      if (!csvDryRun.value) {
        await refreshPortfolioData();
      }
    } catch (err) {
      error.value = getParsedApiError(err);
    } finally {
      csvCommitting.value = false;
    }
  }

  function openDeleteDialog(item: PendingDelete): void {
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行删除修正。';
      return;
    }
    pendingDelete.value = item;
  }

  async function handleConfirmDelete(): Promise<void> {
    if (!pendingDelete.value || deleteLoading.value) return;
    if (!writableAccountId.value) {
      writeWarning.value = '请先在右上角选择具体账户，再进行删除修正。';
      pendingDelete.value = null;
      return;
    }

    const pd = pendingDelete.value;
    const nextPage =
      currentEventCount.value === 1 && eventPage.value > 1 ? eventPage.value - 1 : eventPage.value;
    try {
      deleteLoading.value = true;
      writeWarning.value = null;
      if (pd.eventType === 'trade') {
        await portfolioApi.deleteTrade(pd.id);
      } else if (pd.eventType === 'cash') {
        await portfolioApi.deleteCashLedger(pd.id);
      } else {
        await portfolioApi.deleteCorporateAction(pd.id);
      }
      pendingDelete.value = null;
      if (nextPage !== eventPage.value) {
        eventPage.value = nextPage;
      }
      await refreshPortfolioData(nextPage);
    } catch (err) {
      error.value = getParsedApiError(err);
    } finally {
      deleteLoading.value = false;
    }
  }

  async function handleCreateAccount(e: Event): Promise<void> {
    e.preventDefault();
    const name = accountForm.value.name.trim();
    if (!name) {
      accountCreateError.value = '账户名称不能为空。';
      accountCreateSuccess.value = null;
      return;
    }
    try {
      accountCreating.value = true;
      accountCreateError.value = null;
      accountCreateSuccess.value = null;
      const af = accountForm.value;
      const created = await portfolioApi.createAccount({
        name,
        broker: af.broker.trim() || undefined,
        market: af.market,
        baseCurrency: af.baseCurrency.trim() || 'CNY',
      });
      await loadAccounts();
      selectedAccount.value = created.id;
      showCreateAccount.value = false;
      writeWarning.value = null;
      accountForm.value = {
        name: '',
        broker: 'Demo',
        market: af.market,
        baseCurrency: af.baseCurrency,
      };
      accountCreateSuccess.value = '账户创建成功，已自动切换到该账户。';
    } catch (err) {
      const parsed = getParsedApiError(err);
      accountCreateError.value = parsed.message || '创建账户失败，请稍后重试。';
      accountCreateSuccess.value = null;
    } finally {
      accountCreating.value = false;
    }
  }

  async function handleRefresh(): Promise<void> {
    await Promise.all([loadAccounts(), loadSnapshotAndRisk(), loadEvents(), loadBrokers()]);
  }

  async function handleRefreshFx(): Promise<void> {
    if (!hasAccounts.value || isLoading.value || fxRefreshing.value) {
      return;
    }

    const requestedViewKey = refreshViewKey.value;
    const requestedAccountId = queryAccountId.value;
    const requestedCostMethod = costMethod.value;
    const requestedRequestId = refreshContext.value.requestId + 1;
    refreshContext.value = {
      viewKey: requestedViewKey,
      requestId: requestedRequestId,
    };

    try {
      fxRefreshing.value = true;
      fxRefreshFeedback.value = null;
      const result = await portfolioApi.refreshFx({
        accountId: requestedAccountId,
      });
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      const reloaded = await reloadSnapshotAndRiskForScope(
        requestedViewKey,
        requestedRequestId,
        requestedAccountId,
        requestedCostMethod,
      );
      if (!reloaded || !isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      fxRefreshFeedback.value = buildFxRefreshFeedback(result);
    } catch (err) {
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      error.value = getParsedApiError(err);
    } finally {
      if (isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        fxRefreshing.value = false;
      }
    }
  }

  function toggleCreateAccountPanel(): void {
    showCreateAccount.value = !showCreateAccount.value;
    accountCreateError.value = null;
    accountCreateSuccess.value = null;
  }

  function closeCreateAccountPanel(): void {
    showCreateAccount.value = false;
    accountCreateError.value = null;
    accountCreateSuccess.value = null;
  }

  function dismissError(): void {
    error.value = null;
  }

  function cancelPendingDelete(): void {
    if (!deleteLoading.value) {
      pendingDelete.value = null;
    }
  }

  function onCsvFileChange(e: Event): void {
    const input = e.target as HTMLInputElement;
    csvFile.value = input.files?.[0] ?? null;
  }

  function prevEventPage(): void {
    eventPage.value = Math.max(1, eventPage.value - 1);
  }

  function nextEventPage(): void {
    eventPage.value = Math.min(totalEventPages.value, eventPage.value + 1);
  }

  watch(
    refreshViewKey,
    (key) => {
      refreshContext.value = {
        viewKey: key,
        requestId: refreshContext.value.requestId + 1,
      };
      fxRefreshing.value = false;
      fxRefreshFeedback.value = null;
    },
    { immediate: true },
  );

  watch(
    () => [
      eventType.value,
      queryAccountId.value,
      eventDateFrom.value,
      eventDateTo.value,
      eventSymbol.value,
      eventSide.value,
      eventDirection.value,
      eventActionType.value,
    ],
    () => {
      if (eventPage.value !== 1) {
        eventPage.value = 1;
      } else {
        void loadEventsPage(1);
      }
    },
  );

  watch(eventPage, (page) => {
    void loadEventsPage(page);
  });

  watch([queryAccountId, costMethod], () => {
    void loadSnapshotAndRisk();
  });

  watch(writeBlocked, (blocked) => {
    if (!blocked) {
      writeWarning.value = null;
    }
  });

  onMounted(() => {
    document.title = '持仓分析 - DSA';
    void loadAccounts();
    void loadBrokers();
    void loadSnapshotAndRisk();
    void loadEventsPage(eventPage.value);
  });

  watch(selectedBroker, () => {
    void loadAccounts();
    void loadBrokers();
  });

  return {
    accounts,
    selectedAccountModel,
    showCreateAccount,
    accountCreating,
    accountCreateError,
    accountCreateSuccess,
    accountForm,
    costMethod,
    snapshot,
    risk,
    isLoading,
    fxRefreshing,
    fxRefreshFeedback,
    error,
    riskWarning,
    writeWarning,
    brokers,
    selectedBroker,
    csvFile,
    csvDryRun,
    csvParsing,
    csvCommitting,
    csvParseResult,
    csvCommitResult,
    brokerLoadWarning,
    eventType,
    eventDateFrom,
    eventDateTo,
    eventSymbol,
    eventSide,
    eventDirection,
    eventActionType,
    eventPage,
    eventLoading,
    tradeEvents,
    cashEvents,
    corporateEvents,
    pendingDelete,
    deleteLoading,
    tradeForm,
    cashForm,
    corpForm,
    hasAccounts,
    writableAccount,
    writableAccountId,
    writeBlocked,
    totalEventPages,
    positionRows,
    concentrationPieData,
    concentrationMode,
    concentrationPieChartOption,
    formatMoney,
    formatPct,
    formatSignedPct,
    formatPositionPrice,
    formatPositionMoney,
    getPositionPriceLabel,
    hasPositionPrice,
    formatSideLabel,
    formatCashDirectionLabel,
    formatCorporateActionLabel,
    formatBrokerLabel,
    getFxRefreshFeedbackVariant,
    getCsvParseVariant,
    getCsvCommitVariant,
    loadEvents,
    handleTradeSubmit,
    handleCashSubmit,
    handleCorporateSubmit,
    handleParseCsv,
    handleCommitCsv,
    openDeleteDialog,
    handleConfirmDelete,
    handleCreateAccount,
    handleRefresh,
    handleRefreshFx,
    toggleCreateAccountPanel,
    closeCreateAccountPanel,
    dismissError,
    cancelPendingDelete,
    onCsvFileChange,
    prevEventPage,
    nextEventPage,
  };
}
