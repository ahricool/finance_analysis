import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IntradayStockPanel from '../IntradayStockPanel.vue';
import type { IntradaySnapshot, PatternEvent } from '@/api/intradayMarket';
import type { OverlayCreate } from 'klinecharts';

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock('@/api/intradayMarket', () => ({ fetchIntradayMarket: mocks.fetch }));
vi.mock('klinecharts', () => ({ registerOverlay: vi.fn() }));
const at = Date.parse('2026-10-21T15:00:00Z');
function snapshot(symbol = 'AAPL.US', timestamp = at, price = 100): IntradaySnapshot {
  return { symbol, market: 'US', tradingDate: '2026-10-21', generatedAt: new Date(at).toISOString(), reset: true,
    items: [{ timestamp, open: price, high: price + 1, low: price - 1, close: price, volume: 10,
      turnover: null, confirmed: false, sampled: false, sampleCount: 0, partial: false }],
    quote: { code: symbol, symbol, marketType: 'US', available: true, lastPrice: price }, events: [] };
}
function mountPanel() {
  return mount(IntradayStockPanel, { props: { symbol: 'AAPL.US', market: 'US' }, global: { stubs: { MarketKLineChart: true } } });
}
beforeEach(() => { vi.useFakeTimers(); mocks.fetch.mockReset(); });
afterEach(() => { vi.useRealTimers(); });

describe('inline intraday ownership and incremental updates', () => {
  it('uses the real previous close for CN zero percent and replaces revised source windows', async () => {
    const initial = { ...snapshot('600000.SH'), market: 'CN' as const, fullSnapshot: true };
    initial.quote.preClose = 97;
    const next = { ...initial, reset: false, items: [{ ...initial.items[0]!, timestamp: at + 60_000 }] };
    mocks.fetch.mockResolvedValueOnce(initial).mockResolvedValue(next);
    const panel = mount(IntradayStockPanel, { props: { symbol: '600000.SH', market: 'CN' },
      global: { stubs: { MarketKLineChart: true } } });
    await flushPromises();
    const chart = () => panel.findComponent({ name: 'MarketKLineChart' });
    expect(chart().props('referencePrice')).toBe(97);
    expect(chart().props('session')).toMatchObject({ open: Date.parse('2026-10-21T09:30:00+08:00'),
      close: Date.parse('2026-10-21T15:00:00+08:00') });
    expect(chart().props('overlays')).toMatchObject([{ name: 'intradayBaseline', points: [{ value: 97 }] }]);
    await vi.advanceTimersByTimeAsync(5_000);
    await flushPromises();
    expect(panel.text()).toContain('已采集 1 根');
    expect(chart().props('current').timestamp).toBe(at + 60_000);
    panel.unmount();
  });
  it('judges live updates every second and detects a stopped feed just after the 30-second tolerance', async () => {
    vi.setSystemTime(at);
    const initial = snapshot();
    initial.quote.trend1m = { timeframe: '1m', targetPeriod: 20, effectivePeriod: 20, minimumPeriod: 5,
      state: 'above', streak: 5, confirmed: true, barTime: new Date(at - 60_000).toISOString() };
    initial.quote.pattern1m = { timeframe: '1m', status: 'none', signal: null };
    const fresh = () => ({ ...initial, reset: false, quote: { ...initial.quote,
      eventTime: new Date().toISOString(), receivedAt: new Date().toISOString() } });
    mocks.fetch.mockImplementation(async () => fresh());
    const panel = mountPanel();
    await flushPromises();
    const direction = () => panel.findComponent({ name: 'IntradayDirectionStatus' }).text();
    expect(direction()).toBe('震荡等待');
    // The former 60-second clock would treat these genuine live updates as future data.
    await vi.advanceTimersByTimeAsync(35_000);
    expect(direction()).toBe('震荡等待');
    mocks.fetch.mockResolvedValue(fresh());
    await vi.advanceTimersByTimeAsync(30_000);
    expect(direction()).toBe('震荡等待');
    await vi.advanceTimersByTimeAsync(1_000);
    expect(direction()).toBe('行情延迟');
    mocks.fetch.mockImplementation(async () => fresh());
    await vi.advanceTimersByTimeAsync(4_000);
    expect(direction()).toBe('震荡等待');
    panel.unmount();
  });

  it('opens evidence and levels only after a marker click, preserves grouped events and clears selection on reset', async () => {
    const initial = snapshot();
    const signal: PatternEvent = { timeframe: '1m', patternType: 'breakout_retest_continuation', patternName: '突破回踩延续',
      direction: 'bullish_continuation', stage: 'confirmed', qualityScore: 83, occurredAt: new Date(at - 600_000).toISOString(),
      observedAt: new Date(at + 20_000).toISOString(), barsAgo: 0, sessionMinutesAgo: 0,
      referenceLevel: 100, invalidationPrice: 98, reasons: ['突破后回踩守住参考位'], confirmed: true };
    initial.events = [{ ...signal, observedAt: new Date(at + 10_000).toISOString(), patternName: '压缩观察',
      direction: 'neutral_wait', stage: 'forming', confirmed: false }, signal];
    initial.quote.pattern1m = { timeframe: '1m', status: 'active', signal };
    mocks.fetch.mockResolvedValueOnce(initial).mockResolvedValueOnce({ ...initial, reset: false }).mockResolvedValue(initial);
    const panel = mountPanel();
    await flushPromises();
    const overlays = () => panel.findComponent({ name: 'MarketKLineChart' }).props('overlays') as OverlayCreate[];
    expect(panel.find('[data-testid="intraday-pattern-evidence"]').exists()).toBe(false);
    expect(overlays()).toHaveLength(1);
    expect(overlays()[0]!.name).toBe('intradayPattern');
    overlays()[0]!.onClick!({} as never);
    await panel.vm.$nextTick();
    const detail = panel.get('[data-testid="intraday-pattern-evidence"]');
    expect(detail.text()).toContain('突破后回踩守住参考位');
    expect(overlays().filter(overlay => overlay.groupId === 'intraday-levels')).toHaveLength(2);
    const group = detail.get('[aria-label="同一分钟的形态事件"]');
    await group.findAll('button')[1]!.trigger('click');
    expect(detail.get('strong').text()).toContain('压缩观察 · 形成中');
    await vi.advanceTimersByTimeAsync(5_000);
    await flushPromises();
    expect(detail.get('strong').text()).toContain('压缩观察');
    await detail.findAll('button')[0]!.trigger('click');
    expect(panel.find('[data-testid="intraday-pattern-evidence"]').exists()).toBe(false);
    expect(overlays()).toHaveLength(1);
    overlays()[0]!.onClick!({} as never);
    await panel.vm.$nextTick();
    await vi.advanceTimersByTimeAsync(5_000);
    await flushPromises();
    expect(panel.find('[data-testid="intraday-pattern-evidence"]').exists()).toBe(false);
    expect(overlays()).toHaveLength(1);
    panel.unmount();
  });

  it('loads only while mounted and merges the closing current minute', async () => {
    const initial = snapshot();
    const next = snapshot('AAPL.US', at + 60_000, 101);
    next.reset = false;
    next.items.unshift({ ...initial.items[0]!, confirmed: true });
    mocks.fetch.mockResolvedValueOnce(initial).mockResolvedValue(next);
    const panel = mountPanel();
    await flushPromises();
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5_000);
    await flushPromises();
    expect(mocks.fetch.mock.calls[1]?.[1]).toBe(new Date(at).toISOString());
    expect(panel.text()).toContain('已采集 2 根');
    const signal = mocks.fetch.mock.calls[1]?.[2] as AbortSignal;
    panel.unmount();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.fetch).toHaveBeenCalledTimes(2);
    expect(signal).toBeDefined();
  });

  it('aborts old symbols and ignores late responses after a switch', async () => {
    let resolveOld!: (value: IntradaySnapshot) => void;
    mocks.fetch.mockReturnValueOnce(new Promise<IntradaySnapshot>(resolve => { resolveOld = resolve; }));
    mocks.fetch.mockResolvedValue(snapshot('MSFT.US', at, 120));
    const panel = mountPanel();
    const oldSignal = mocks.fetch.mock.calls[0]?.[2] as AbortSignal;
    await panel.setProps({ symbol: 'MSFT.US' });
    await flushPromises();
    expect(oldSignal.aborted).toBe(true);
    resolveOld(snapshot('AAPL.US', at, 999));
    await flushPromises();
    expect(panel.text()).toContain('120');
    expect(panel.text()).not.toContain('999');
    panel.unmount();
  });
});
