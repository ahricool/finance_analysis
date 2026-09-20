import { defineComponent } from 'vue';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Constituents, IndustryDetail, IndustryHistory, IndustryRanking, IndustrySnapshot } from '@/api/industryStrength';
import { useIndustryStrength } from '../useIndustryStrength';

const api = vi.hoisted(() => ({ ranking: vi.fn(), dates: vi.fn(), history: vi.fn(), detail: vi.fn(), constituents: vi.fn() }));
vi.mock('@/api/industryStrength', () => ({ industryStrengthApi: api }));

function row(code = '881101.TI', name = '行业甲', rank = 1, tradeDate = '2026-09-16', overrides: Partial<IndustrySnapshot> = {}): IndustrySnapshot {
  return {
    tradeDate, industryCode: code, industryName: name, state: rank === 1 ? 'STRONG' : 'NEUTRAL', close: 100,
    strengthRank: rank, strengthScore: 90 - rank, ret1D: rank === 1 ? 0.01 : -0.01, ret5D: 0.03, ret10D: 0.04, ret20D: 0.05,
    rs5D: 0.01, rs10D: 0.02, rs20D: 0.03, rankChange1D: rank === 1 ? 2 : 0, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: 0.01, momentumAcceleration5D: rank === 1 ? 0.02 : -0.03, accelerationPercentile: 80, turnoverRatio5D: 1.2,
    upRatio: 0.7, aboveMa5Ratio: 0.8, aboveMa20Ratio: 0.9, equalWeightReturn: 0.01,
    constituentCount: 10, dailyValidCount: 10, ma5ValidCount: 10, aboveMa5Count: 8, ma20ValidCount: 10, aboveMa20Count: 9,
    upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: `${tradeDate}T07:00:00Z`, membersObservedAt: `${tradeDate}T11:00:00Z`,
    createdAt: `${tradeDate}T11:05:00Z`, updatedAt: `${tradeDate}T11:05:00Z`,
    quality: { dailyBreadthCoverage: 1, ma5Coverage: 1, ma20Coverage: 1, catalogCount: 2, rankedCount: 2, coverage: 1, excluded: {} },
    ...overrides,
  };
}

const t = '2026-09-16';
const t1 = '2026-09-15';
const a = row('881101.TI', '行业甲', 1, t);
const b = row('881102.TI', '行业乙', 2, t);
const aT1 = row('881101.TI', '行业甲', 1, t1, { strengthScore: 77 });
const bT1 = row('881102.TI', '行业乙', 2, t1, { strengthScore: 66 });

function rankingOf(tradeDate: string, items: IndustrySnapshot[]): IndustryRanking {
  return { tradeDate, expectedTradeDate: t, source: 'snapshot', items };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function members(code: string, tradeDate: string): Constituents {
  return {
    industryCode: code, tradeDate, membersObservedAt: `${tradeDate}T11:00:00Z`,
    constituentCount: 1, dailyValidCount: 1, ma5ValidCount: 1, aboveMa5Count: 1, ma20ValidCount: 1, aboveMa20Count: 1,
    items: [],
  };
}

let host: VueWrapper | undefined;

function setup() {
  let page!: ReturnType<typeof useIndustryStrength>;
  host = mount(defineComponent({ setup() { page = useIndustryStrength(); return () => null; } }));
  return page;
}

afterEach(() => {
  host?.unmount();
  host = undefined;
});

beforeEach(() => {
  vi.clearAllMocks();
  api.dates.mockResolvedValue([t, t1]);
  api.ranking.mockResolvedValue(rankingOf(t, [a, b]));
  api.history.mockResolvedValue({ dates: [t], items: [a, b] } satisfies IndustryHistory);
  api.detail.mockImplementation(async (code: string, tradeDate?: string) => {
    const current = [a, b, aT1, bT1].find((item) => item.industryCode === code && item.tradeDate === (tradeDate ?? t)) ?? a;
    return { current, history: [{ ...current, tradeDate: '2026-08-01', strengthScore: 12.34 }] } satisfies IndustryDetail;
  });
  api.constituents.mockImplementation(async (code: string) => members(code, '2026-09-17'));
});

describe('useIndustryStrength races', () => {
  it('loads detail and members independently and retries detail without reloading members', async () => {
    const page = setup();
    await page.loadRanking('initial');
    const pending = deferred<IndustryDetail>();
    api.detail.mockReturnValueOnce(pending.promise);
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(page.detailLoading.value).toBe(true);
    expect(page.membersLoading.value).toBe(false);
    expect(page.constituents.value?.industryCode).toBe(a.industryCode);
    pending.reject(new Error('detail offline'));
    await flushPromises();
    expect(page.detailError.value).toBeTruthy();
    page.retryDetail();
    await flushPromises();
    expect(page.matchedDetail.value?.current.industryCode).toBe(a.industryCode);
    expect(api.constituents).toHaveBeenCalledTimes(1);
  });

  it('clears previous members and ignores stale successes and failures when switching industries', async () => {
    const page = setup();
    await page.loadRanking('initial');
    page.openIndustry(a.industryCode);
    await flushPromises();
    const pendingB = deferred<Constituents>();
    api.constituents.mockReturnValueOnce(pendingB.promise);
    page.openIndustry(b.industryCode);
    expect(page.constituents.value).toBeNull();
    expect(page.membersLoading.value).toBe(true);
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(page.constituents.value?.industryCode).toBe(a.industryCode);
    pendingB.resolve(members(b.industryCode, 'OLD-B'));
    await flushPromises();
    expect(page.constituents.value?.industryCode).toBe(a.industryCode);
    const failedB = deferred<Constituents>();
    api.constituents.mockReturnValueOnce(failedB.promise);
    page.openIndustry(b.industryCode);
    page.openIndustry(a.industryCode);
    failedB.reject(new Error('old failure'));
    await flushPromises();
    expect(page.membersError.value).toBeNull();
    expect(page.constituents.value?.industryCode).toBe(a.industryCode);
  });

  it('reuses members on date changes and reopening but invalidates cache after refresh', async () => {
    const page = setup();
    await page.loadRanking('initial');
    page.openIndustry(a.industryCode);
    await flushPromises();
    api.ranking.mockResolvedValueOnce(rankingOf(t1, [aT1, bT1]));
    page.changeDate(t1);
    await flushPromises();
    expect(page.matchedDetail.value?.current.tradeDate).toBe(t1);
    expect(api.constituents).toHaveBeenCalledTimes(1);
    page.setDialogOpen(false);
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(api.constituents).toHaveBeenCalledTimes(1);
    await page.refresh();
    await flushPromises();
    expect(api.constituents).toHaveBeenCalledTimes(2);
  });

  it('does not keep industry A detail under industry B while B is pending', async () => {
    const page = setup();
    await page.loadRanking('initial');
    await flushPromises();
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(page.matchedDetail.value?.current.industryCode).toBe(a.industryCode);
    expect(page.matchedDetail.value?.history[0]?.strengthScore).toBe(12.34);

    const pending = deferred<IndustryDetail>();
    api.detail.mockReturnValueOnce(pending.promise);
    page.openIndustry(b.industryCode);
    await flushPromises();
    expect(page.selected.value).toBe(b.industryCode);
    expect(page.matchedDetail.value).toBeNull();
    expect(page.selectedRow.value?.industryName).toBe('行业乙');
    expect(page.detail.value).toBeNull();
    pending.resolve({ current: b, history: [{ ...b, tradeDate: '2026-08-02', strengthScore: 55 }] });
    await flushPromises();
    expect(page.matchedDetail.value?.current.industryCode).toBe(b.industryCode);
    expect(page.matchedDetail.value?.history[0]?.tradeDate).toBe('2026-08-02');
  });

  it('does not keep A@T history after a failed detail request for A@T-1', async () => {
    const page = setup();
    await page.loadRanking('initial');
    await flushPromises();
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(page.matchedDetail.value?.history[0]?.tradeDate).toBe('2026-08-01');

    api.ranking.mockResolvedValueOnce(rankingOf(t1, [aT1, bT1]));
    api.history.mockResolvedValueOnce({ dates: [t1], items: [aT1, bT1] });
    api.detail.mockRejectedValueOnce(new Error('detail offline'));
    page.changeDate(t1);
    await flushPromises();
    expect(page.ranking.value?.tradeDate).toBe(t1);
    expect(page.matchedDetail.value).toBeNull();
    expect(page.detail.value).toBeNull();
    expect(page.detailError.value).toBeTruthy();
    expect(page.selectedRow.value?.tradeDate).toBe(t1);
  });

  it('keeps A@T detail during same-day refresh', async () => {
    const page = setup();
    await page.loadRanking('initial');
    await flushPromises();
    page.openIndustry(a.industryCode);
    await flushPromises();
    const pending = deferred<IndustryDetail>();
    api.detail.mockReturnValueOnce(pending.promise);
    api.ranking.mockResolvedValueOnce(rankingOf(t, [a, b]));
    api.history.mockResolvedValueOnce({ dates: [t], items: [a, b] });
    await page.refresh();
    await flushPromises();
    expect(page.matchedDetail.value?.current.tradeDate).toBe(t);
    expect(page.matchedDetail.value?.history[0]?.strengthScore).toBe(12.34);
    expect(page.detailLoading.value).toBe(true);
    pending.resolve({ current: a, history: [{ ...a, tradeDate: '2026-08-01', strengthScore: 12.34 }] });
    await flushPromises();
    expect(page.matchedDetail.value?.current.industryCode).toBe(a.industryCode);
  });

  it('does not render T history as T-1 while the new history request is pending or failed', async () => {
    const page = setup();
    const firstHistory = deferred<IndustryHistory>();
    api.history.mockReturnValueOnce(firstHistory.promise);
    await page.loadRanking('initial');
    await flushPromises();
    firstHistory.resolve({ dates: [t, '2026-09-14'], items: [a, b] });
    await flushPromises();
    expect(page.chartHistory.value.dates).toEqual([t, '2026-09-14']);

    const nextHistory = deferred<IndustryHistory>();
    api.ranking.mockResolvedValueOnce(rankingOf(t1, [aT1, bT1]));
    api.history.mockReturnValueOnce(nextHistory.promise);
    page.changeDate(t1);
    await flushPromises();
    expect(page.ranking.value?.tradeDate).toBe(t1);
    expect(page.chartHistory.value.dates).toEqual([]);
    expect(page.historyLoading.value).toBe(true);

    api.history.mockRejectedValueOnce(new Error('history offline'));
    nextHistory.reject(new Error('history offline'));
    await flushPromises();
    expect(page.chartHistory.value.dates).toEqual([]);
    expect(page.historyError.value).toBeTruthy();
    expect(page.historyEndTradeDate.value).toBe(t1);
  });

  it('drops an in-flight T history after switching to an empty ranking date', async () => {
    const page = setup();
    const pendingHistory = deferred<IndustryHistory>();
    api.history.mockReset();
    api.history.mockImplementation(() => pendingHistory.promise);
    await page.loadRanking('initial');
    await flushPromises();
    expect(api.history).toHaveBeenCalledTimes(1);
    expect(page.historyLoading.value).toBe(true);

    api.ranking.mockResolvedValueOnce({ tradeDate: null, expectedTradeDate: t, source: 'snapshot', items: [] });
    page.changeDate('2026-09-01');
    await flushPromises();
    pendingHistory.resolve({ dates: [t], items: [a, b] });
    await flushPromises();
    expect(page.chartHistory.value.dates).toEqual([]);
    expect(page.history.value.dates).toEqual([]);
  });

  it('does not write a stale constituents response back into the cache after refresh', async () => {
    const page = setup();
    await page.loadRanking('initial');
    await flushPromises();
    const stale = deferred<Constituents>();
    api.constituents.mockReturnValueOnce(stale.promise);
    page.openIndustry(a.industryCode);
    await flushPromises();
    expect(page.membersLoading.value).toBe(true);

    const fresh = deferred<Constituents>();
    api.ranking.mockResolvedValueOnce(rankingOf(t, [a, b]));
    api.history.mockResolvedValueOnce({ dates: [t], items: [a, b] });
    api.constituents.mockReturnValueOnce(fresh.promise);
    await page.refresh();
    await flushPromises();
    stale.resolve(members(a.industryCode, 'STALE-DATE'));
    await flushPromises();
    expect(page.constituents.value?.tradeDate).not.toBe('STALE-DATE');
    fresh.resolve(members(a.industryCode, 'FRESH-DATE'));
    await flushPromises();
    expect(page.constituents.value?.tradeDate).toBe('FRESH-DATE');
  });
});
