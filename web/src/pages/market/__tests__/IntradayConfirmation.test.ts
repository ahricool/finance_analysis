import { createPinia, setActivePinia } from 'pinia';
import { useMarketStore } from '@/stores/marketStore';
import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from '../IntradayConfirmationPage.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import { intradayConfirmationApi as api, type Snapshot } from '@/api/intradayConfirmation';
vi.mock('@/api/intradayConfirmation', () => ({ intradayConfirmationApi: { read: vi.fn(), dates: vi.fn(), run: vi.fn() } }));
const auth = vi.hoisted(() => ({ currentUser: { role: 'user' } }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => auth }));
beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia()); vi.resetAllMocks(); auth.currentUser.role = 'user'; vi.mocked(api.dates).mockResolvedValue({ dates: ['2026-09-21', '2026-09-18'] }); });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
const snapshot = { market: 'US', tradeDate: '2026-09-21', candidateTradeDate: '2026-09-18', status: 'evaluated',
  generatedAt: '2026-09-21T14:00:00Z', frozenAt: '2026-09-21T13:25:00Z', warnings: [],
  summary: { total: 1, confirmed: 1, wait: 0, failed: 0 }, rulesNote: 'V1 启发式规则，未经回测验证',
  items: [{ code: 'ABC.US', name: 'ABC', candidateSource: 'trend', candidateTradeDate: '2026-09-18',
    candidateReason: ['昨日 CANDIDATE'], state: 'CONFIRMED', confirmationScore: 90, chaseRisk: 'HIGH',
    reasons: [{ code: 'vwap', text: '价格高于 VWAP' }], stateReasons: [], metrics: { return5M: .01, return15M: null,
      quoteTime: '2026-09-21T13:45:00Z', volumeRatio: 1.6 }, trend: { impact: 'intact' } }] };
describe('intraday confirmation page', () => {
  it('shows dates, candidate reasons, unavailable and independent high chase risk', async () => {
    vi.mocked(api.read).mockResolvedValue(snapshot as never);
    const wrapper = mount(Page);
    await flushPromises();
    expect(wrapper.text()).toContain('趋势前30');
    expect(wrapper.text()).toContain('2026-09-18');
    expect(wrapper.text()).toContain('曾经确认');
    expect(wrapper.text()).toContain('高');
    expect(wrapper.text()).toContain('—');
    expect(wrapper.text()).toContain('Yahoo 可能延迟');
    expect(wrapper.text()).not.toContain('运行当日确认任务');
    expect(api.run).not.toHaveBeenCalled();
    await wrapper.get('select[aria-label="状态"]').setValue('FAILED');
    await flushPromises();
    expect(api.read).toHaveBeenLastCalledWith('CN', 'FAILED', undefined, undefined, expect.any(AbortSignal));
    expect(wrapper.find('select[aria-label="市场"]').exists()).toBe(false);
    useMarketStore().market = 'US';
    await flushPromises();
    expect(api.read).toHaveBeenLastCalledWith('US', 'FAILED', undefined, undefined, expect.any(AbortSignal));
    useMarketStore().market = 'CN';
    await flushPromises();
    expect(api.read).toHaveBeenLastCalledWith('CN', 'FAILED', undefined, undefined, expect.any(AbortSignal));
    wrapper.unmount();
  });
  it('renders an unavailable current observation without implying low risk or losing confirmation', async () => {
    vi.mocked(api.read).mockResolvedValue({ ...snapshot, items: [{ ...snapshot.items[0],
      confirmationScore: null, availableScoreWeight: 0, chaseRisk: 'UNKNOWN',
      reasons: [{ code: 'data_unavailable', text: '行情不可用' }],
    }] } as never);
    const wrapper = mount(Page);
    await flushPromises();
    const row = wrapper.get('tbody tr');
    expect(row.text()).toContain('曾经确认');
    expect(row.text()).toContain('—');
    expect(row.text()).toContain('有效权重 0/100');
    const risk = row.findAll('td').find(cell => cell.text() === '待评估');
    expect(risk?.classes()).toContain('text-muted-foreground');
    expect(row.text()).not.toContain('LOW');
    wrapper.unmount();
  });
  it('shows missed preopen freeze as an empty pool', async () => {
    vi.mocked(api.read).mockResolvedValue({ ...snapshot, status: 'not_frozen', items: [] } as never);
    const wrapper = mount(Page);
    await flushPromises();
    expect(wrapper.text()).toContain('开盘后不会根据涨幅补建候选');
    wrapper.unmount();
  });
});

it('opens the shared intraday tab and preserves the observation date', async () => {
  vi.mocked(api.read).mockResolvedValue(snapshot as never);
  const wrapper = mount(Page, { global: { stubs: { StockDetailDialog: true } } });
  await flushPromises();
  await wrapper.get('tbody button').trigger('click');
  const dialog = wrapper.getComponent(StockDetailDialog);
  expect(dialog.props('open')).toBe(true);
  expect(dialog.props('initialTab')).toBe('overview');
  await wrapper.get('tbody tr').trigger('click');
  expect(dialog.props('initialTab')).toBe('intraday');
  expect(dialog.props('context')).toEqual({ tradeDate: '2026-09-21' });
  expect(dialog.props('stock')).toMatchObject({ code: 'ABC.US' });
  dialog.vm.$emit('update:open', false);
  await flushPromises();
  expect(dialog.props('open')).toBe(false);
  wrapper.unmount();
});


describe('intraday history and confirmed-price returns', () => {
  it('renders real zero separately from missing returns and passes the selected history date', async () => {
    vi.mocked(api.read).mockResolvedValue({ ...snapshot, items: [{ ...snapshot.items[0], return3D: .1234, return5D: 0, return10D: null }] } as never);
    const wrapper = mount(Page, { global: { stubs: { StockDetailDialog: true } } });
    await flushPromises();
    expect(wrapper.get('[data-testid="intraday-return-3d"]').text()).toBe('12.34%');
    expect(wrapper.get('[data-testid="intraday-return-5d"]').text()).toBe('0.00%');
    expect(wrapper.get('[data-testid="intraday-return-10d"]').text()).toBe('');
    await wrapper.get('[data-testid="intraday-date-selector"]').setValue('2026-09-18'); await flushPromises();
    expect(api.read).toHaveBeenLastCalledWith('CN', undefined, undefined, '2026-09-18', expect.any(AbortSignal));
    expect(wrapper.text()).toContain('历史快照 2026-09-18');
    expect(wrapper.text()).toContain('首次确认价格起算');
    wrapper.unmount();
  });
  it('cancels and ignores stale date/market requests, resets history on market changes and closes detail', async () => {
    vi.mocked(api.read).mockResolvedValue(snapshot as never);
    const wrapper = mount(Page, { global: { stubs: { StockDetailDialog: true } } });
    await flushPromises();
    await wrapper.get('tbody button').trigger('click');
    expect(wrapper.getComponent(StockDetailDialog).props('open')).toBe(true);
    const old = deferred<Snapshot>();
    vi.mocked(api.read).mockReturnValueOnce(old.promise);
    await wrapper.get('[data-testid="intraday-date-selector"]').setValue('2026-09-18');
    expect(wrapper.getComponent(StockDetailDialog).props('open')).toBe(false);
    const signal = vi.mocked(api.read).mock.calls.at(-1)![4]!;
    const oldDates = deferred<{ dates: string[] }>();
    vi.mocked(api.dates).mockReturnValueOnce(oldDates.promise);
    useMarketStore().market = 'US';
    await flushPromises();
    expect(signal.aborted).toBe(true);
    expect(api.read).toHaveBeenLastCalledWith('US', undefined, undefined, undefined, expect.any(AbortSignal));
    expect((wrapper.get('select[aria-label="交易日"]').element as HTMLSelectElement).value).toBe('');
    const datesSignal = vi.mocked(api.dates).mock.calls.at(-1)![1]!;
    useMarketStore().market = 'CN'; await flushPromises();
    expect(datesSignal.aborted).toBe(true);
    old.resolve({ ...snapshot, tradeDate: '1999-01-01' } as unknown as Snapshot);
    oldDates.resolve({ dates: ['1999-01-01'] }); await flushPromises();
    expect(wrapper.text()).not.toContain('1999-01-01');
    const lastSignal = vi.mocked(api.read).mock.calls.at(-1)![4]!;
    wrapper.unmount(); expect(lastSignal.aborted).toBe(true);
  });
  it('shows date-list failure independently and supports retry while keeping the snapshot', async () => {
    vi.mocked(api.read).mockResolvedValue(snapshot as never);
    vi.mocked(api.dates).mockRejectedValueOnce(new Error('offline'));
    const wrapper = mount(Page); await flushPromises();
    expect(wrapper.text()).toContain('趋势前30');
    await wrapper.findAll('button').find(button => button.text() === '重试历史日期')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).not.toContain('重试历史日期');
    expect(wrapper.get('select[aria-label="交易日"]').findAll('option')).toHaveLength(3);
    wrapper.unmount();
  });
  it('only runs today and ignores an old market task response', async () => {
    auth.currentUser.role = 'admin';
    vi.mocked(api.read).mockResolvedValue(snapshot as never);
    const old = deferred<{ taskId: string }>(); vi.mocked(api.run).mockReturnValueOnce(old.promise);
    const wrapper = mount(Page); await flushPromises();
    const run = wrapper.findAll('button').find(button => button.text() === '运行当日确认任务')!;
    await wrapper.get('select[aria-label="交易日"]').setValue('2026-09-18'); await flushPromises();
    expect(run.attributes('disabled')).toBeDefined();
    await run.trigger('click'); expect(api.run).not.toHaveBeenCalled();
    await wrapper.get('select[aria-label="交易日"]').setValue(''); await flushPromises();
    await run.trigger('click'); expect(api.run).toHaveBeenCalledWith('CN');
    useMarketStore().market = 'US'; await flushPromises();
    old.resolve({ taskId: 'stale-cn-task' }); await flushPromises();
    expect(wrapper.text()).not.toContain('stale-cn-task');
    wrapper.unmount();
  });
});

it('separates current weakness from the historical confirmation and retains every source', async () => {
  vi.mocked(api.read).mockResolvedValue({ ...snapshot, ruleVersion: 'intraday_v2', items: [{ ...snapshot.items[0],
    currentStatus: 'WEAKENING', firstConfirmedAt: '2026-09-21T14:00:00Z', candidateSources: ['confluence', 'etf'], instrumentType: 'ETF',
  }] } as never);
  const wrapper = mount(Page); await flushPromises();
  expect(wrapper.get('tbody').text()).toContain('确认后走弱');
  expect(wrapper.get('tbody').text()).toContain('曾经确认');
  expect(wrapper.get('tbody').text()).toContain('共振精选');
  expect(wrapper.get('tbody').text()).toContain('轮动前5');
  await wrapper.get('select[aria-label="当前观察"]').setValue('ACTIVE');
  expect(wrapper.get('tbody').text()).toContain('没有符合筛选条件');
  await wrapper.get('select[aria-label="当前观察"]').setValue('');
  await wrapper.get('input[aria-label="搜索候选"]').setValue('nomatch');
  expect(wrapper.get('tbody').text()).toContain('没有符合筛选条件');
  wrapper.unmount();
});

it('distinguishes pending directions and filters them independently', async () => {
  vi.mocked(api.read).mockResolvedValue({ ...snapshot, ruleVersion: 'intraday_v2', items: [
    { ...snapshot.items[0], code: 'UP.US', name: '走强样本', state: 'WAIT', currentStatus: 'PENDING_CONFIRMATION' },
    { ...snapshot.items[0], code: 'TMO.US', name: '失效样本', state: 'WAIT', currentStatus: 'PENDING_FAILURE', confirmationScore: 3.81 },
  ] } as never);
  const wrapper = mount(Page); await flushPromises();
  expect(wrapper.get('tbody').text()).toContain('走强待确认');
  expect(wrapper.get('tbody').text()).toContain('失效待确认');
  await wrapper.get('select[aria-label="当前观察"]').setValue('PENDING_FAILURE');
  expect(wrapper.get('tbody').text()).toContain('TMO.US');
  expect(wrapper.get('tbody').text()).not.toContain('UP.US');
  await wrapper.get('select[aria-label="当前观察"]').setValue('PENDING_CONFIRMATION');
  expect(wrapper.get('tbody').text()).toContain('UP.US');
  expect(wrapper.get('tbody').text()).not.toContain('TMO.US');
  wrapper.unmount();
});

it('sorts the whole filtered snapshot through headers before paging and returns to page one', async () => {
  vi.mocked(api.read).mockResolvedValue({ ...snapshot, items: Array.from({ length: 18 }, (_, index) => ({
    ...snapshot.items[0], code: `ROW${index}.US`, name: `样本${index}`, confirmationScore: index,
    metrics: { ...snapshot.items[0]!.metrics, relativeToMarket: index / 100, intradayReturn: index / 200 },
  })) } as never);
  const wrapper = mount(Page); await flushPromises();
  const body = () => wrapper.get('tbody').findAll('tr');
  expect(body()[0]!.text()).toContain('ROW0.US');
  const score = wrapper.findAll('th').find(header => header.text().includes('确认分'))!;
  await score.get('button').trigger('click');
  expect(score.attributes('aria-sort')).toBe('ascending');
  await score.get('button').trigger('click');
  expect(score.attributes('aria-sort')).toBe('descending');
  expect(body()[0]!.text()).toContain('ROW17.US');
  expect(body()).toHaveLength(15);
  await wrapper.findAll('button').find(button => button.attributes('aria-label') === '下一页')!.trigger('click');
  const rs = wrapper.findAll('th').find(header => header.text().includes('相对大盘'))!;
  await rs.get('button').trigger('click');
  expect(body()[0]!.text()).toContain('ROW0.US');
  expect(body()).toHaveLength(15);
  await wrapper.get('input[aria-label="搜索候选"]').setValue('样本17');
  expect(body()).toHaveLength(1);
  expect(body()[0]!.text()).toContain('ROW17.US');
  wrapper.unmount();
});

it('sorts all three forward-return horizons by their own raw values and keeps missing returns last', async () => {
  vi.mocked(api.read).mockResolvedValue({ ...snapshot, items: [
    { ...snapshot.items[0], code: 'A.US', return3D: .1, return5D: -.2, return10D: .3 },
    { ...snapshot.items[0], code: 'B.US', return3D: -.1, return5D: .2, return10D: -.3 },
    { ...snapshot.items[0], code: 'EMPTY.US', return3D: null, return5D: null, return10D: null },
  ] } as never);
  const wrapper = mount(Page); await flushPromises();
  for (const [days, first] of [[3, 'B.US'], [5, 'A.US'], [10, 'B.US']] as const) {
    const header = wrapper.findAll('th').find(node => node.text().includes(`${days}日收益`))!;
    await header.get('button').trigger('click');
    const rows = wrapper.get('tbody').findAll('tr');
    expect(rows[0]!.text()).toContain(first);
    expect(rows.at(-1)!.text()).toContain('EMPTY.US');
    await header.get('button').trigger('click');
    expect(wrapper.get('tbody').findAll('tr').at(-1)!.text()).toContain('EMPTY.US');
  }
  wrapper.unmount();
});
