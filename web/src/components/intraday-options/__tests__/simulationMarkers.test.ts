import { describe, expect, it, vi } from 'vitest';
import type { IntradayBar } from '@/api/intradayMarket';
import type { SimTrade, SimulationSnapshot } from '@/api/intradayOptions';
import { simulationOperations, simulationMarkers, simulationTradeOverlays } from '../simulationMarkers';
vi.mock('klinecharts', () => ({ registerOverlay: vi.fn() }));
const day = '2026-11-17';
const start = Date.parse(`${day}T17:00:00Z`);
const bar = (offset: number, confirmed = true) => ({ timestamp: start + offset * 60000, low: 99, high: 103, confirmed } as IntradayBar);
const trade = (extra: Partial<SimTrade> = {}): SimTrade => ({ id: 'trade1', symbol: 'QQQ.US', side: 1, kind: 'box_breakout',
  entryAt: `${day}T17:00:00Z`, entryPriceAt: `${day}T16:59:59Z`, entryPrice: 100,
  lastPrice: 102, lastPriceAt: `${day}T17:02:00Z`, invalidation: 99, protection: 101, target: 103, returnPct: 2,
  exitAt: `${day}T17:02:05Z`, exitPriceAt: `${day}T17:02:04Z`, exitPrice: 102, exitReason: '保护位触及', ...extra });
const snapshot = (trades: SimTrade[]): SimulationSnapshot => ({ trades, states: [], events: [], statistics: [] });

describe('intraday simulated B/S markers', () => {
  it.each([1, -1])('maps entry and exit correctly for direction %s, including exact minute boundaries and live bars', side => {
    const operations = simulationOperations(snapshot([trade({ side })]), 'QQQ.US', day);
    expect(operations.map(o => o.action)).toEqual(side === 1 ? ['B', 'S'] : ['S', 'B']);
    expect(operations[0]!.label).toBe(side === 1 ? '模拟做多进场' : '模拟做空进场');
    const markers = simulationMarkers(operations, [bar(-1), bar(0), bar(2, false)]);
    expect(markers.map(m => m.timestamp)).toEqual([start, start + 120000]);
    expect(markers[0]!.operations[0]!.price).toBe(100);
    expect(markers[0]!.operations[0]!.priceAt).toBe(`${day}T16:59:59Z`);
  });
  it('deduplicates reconnect and closed trade copies without losing the exit', () => {
    const closed = trade();
    const entry = trade({ exitAt: undefined, exitPrice: undefined });
    const value = snapshot([closed]);
    value.events = [{ id: 2, kind: 'exit', at: closed.exitAt!, symbol: closed.symbol, reason: '', trade: closed },
      { id: 1, kind: 'entry', at: entry.entryAt, symbol: entry.symbol, reason: '', trade: entry }];
    value.events.push(value.events[0]!);
    value.states = [{ symbol: entry.symbol, position: entry } as SimulationSnapshot['states'][number]];
    expect(simulationOperations(value, 'QQQ.US', day)).toHaveLength(2);
    expect(simulationOperations(snapshot([entry]), 'QQQ.US', day)).toHaveLength(1);
  });
  it('filters other symbols and trading dates, never attaching a gap trade to a neighbouring bar', () => {
    const value = snapshot([trade(), trade({ id: 'other', symbol: 'NVDA.US' }), trade({ id: 'yesterday', entryAt: '2026-11-16T17:00:00Z', exitAt: undefined })]);
    const ops = simulationOperations(value, 'QQQ.US', day);
    expect(ops).toHaveLength(2);
    expect(simulationMarkers(ops, [bar(-1), bar(1)])).toEqual([]);
    expect(simulationOperations(value, 'QQQ.US', '2026-11-18')).toEqual([]);
  });
  it('groups same-minute buy and sell with all details and stable identity', () => {
    const ops = simulationOperations(snapshot([trade({ exitAt: `${day}T17:00:40Z` })]), 'QQQ.US', day);
    const markers = simulationMarkers(ops, [bar(0)]);
    expect(markers).toHaveLength(1);
    expect(markers[0]!.label).toBe('B/S');
    expect(markers[0]!.operations).toHaveLength(2);
    const select = vi.fn();
    const overlays = simulationTradeOverlays(markers, true, select);
    overlays[0]!.onClick!({} as never);
    expect(select).toHaveBeenCalledWith(start);
    expect(overlays[0]!.groupId).toBe('intraday-simulation-trades');
    expect(simulationTradeOverlays(markers, false, select)[0]!.id).toBe(overlays[0]!.id);
  });
  it('marks estimated restart exits at the planned deadline, retaining actual processing and old price times', () => {
    const t = trade({ estimated: true, plannedExitAt: `${day}T19:00:00Z`, exitAt: '2026-11-18T15:00:00Z',
      exitPriceAt: `${day}T18:50:00Z`, anomaly: '重启补记', exitPrice: 101 });
    const ops = simulationOperations(snapshot([t]), 'QQQ.US', day);
    const exit = ops[1]!;
    expect(exit).toMatchObject({ action: 'S', estimated: true, at: t.plannedExitAt, processedAt: t.exitAt, priceAt: t.exitPriceAt, price: 101 });
    expect(exit.reason).toContain('重启补记');
    expect(simulationMarkers(ops, [bar(120)])[0]!.label).toBe('S*');
    expect(simulationOperations(snapshot([t]), 'QQQ.US', '2026-11-18')).toEqual([]);
  });
  it('does not place malformed or unavailable prices on the chart', () => {
    expect(simulationOperations(snapshot([trade({ entryAt: 'bad', exitPrice: NaN })]), 'QQQ.US', day)).toEqual([]);
  });
});
