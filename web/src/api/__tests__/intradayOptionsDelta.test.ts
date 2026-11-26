import { describe, expect, it } from 'vitest';
import { applyIntradayOptionsDelta } from '../intradayOptionsDelta';
import type { IntradayOptionsSnapshot } from '../intradayOptions';
import { toCamelCase } from '../utils';

const snapshot = () => toCamelCase<IntradayOptionsSnapshot>({
  generated_at: 'before', trading_date: '2026-11-25', version: 'v1', market_status: 'closed',
  items: [{ symbol: 'A.US', last_price: 10, result: { score: 80, reasons: ['unchanged'] } }, { symbol: 'B.US', last_price: 20 }],
  simulation: { states: [{ symbol: 'A.US', position: { id: 'trade' } }], trades: [], events: [{ id: 2 }, { id: 1 }], statistics: [] },
});

describe('intraday options delta', () => {
  it('preserves untouched subtrees and atomically applies ordered changes', () => {
    const before = snapshot();
    const after = applyIntradayOptionsDelta(before, { base_revision: 1, revision: 2, operations: [
      { op: 'set', path: ['items', 0, 'last_price'], value: 11 },
      { op: 'remove', path: ['items', 1] },
      { op: 'insert', path: ['items', 1], value: { symbol: 'C.US', last_price: 30 } },
      { op: 'set', path: ['simulation', 'states', 0, 'position'], value: null },
      { op: 'insert', path: ['simulation', 'trades', 0], value: { id: 'trade', exit_price: 11 } },
      { op: 'insert', path: ['simulation', 'events', 0], value: { id: 3, trade_id: 'trade' } },
    ] }, 'after');
    expect(after.generatedAt).toBe('after');
    expect(after.items.map(row => [row.symbol, row.lastPrice])).toEqual([['A.US', 11], ['C.US', 30]]);
    expect(after.items[0]!.result).toBe(before.items[0]!.result);
    expect(after.simulation?.states[0]?.position).toBeNull();
    expect(after.simulation?.trades[0]).toEqual({ id: 'trade', exitPrice: 11 });
    expect(after.simulation?.events.map(event => event.id)).toEqual([3, 2, 1]);
    expect(after.simulation?.events[0]?.tradeId).toBe('trade');
    expect(before.items[0]?.lastPrice).toBe(10);
    expect(before.simulation?.events).toHaveLength(2);
  });

  it('advances only snapshot time on heartbeat; rejects invalid operations without mutating state', () => {
    const before = snapshot();
    const heartbeat = applyIntradayOptionsDelta(before, { base_revision: 1, revision: 2, operations: [] }, 'heartbeat');
    expect(heartbeat.items).toBe(before.items);
    expect(heartbeat.simulation).toBe(before.simulation);
    expect(heartbeat.generatedAt).toBe('heartbeat');
    expect(() => applyIntradayOptionsDelta(before, { base_revision: 1, revision: 2, operations: [
      { op: 'set', path: ['items', 0, 'last_price'], value: 11 },
      { op: 'remove', path: ['items', 99] },
    ] }, 'invalid')).toThrow();
    expect(before.items[0]?.lastPrice).toBe(10);
    expect(() => applyIntradayOptionsDelta(before, { base_revision: 1, revision: 2, operations: [
      { op: 'set', path: ['simulation', 'events'], value: null },
    ] }, 'bad-shape')).toThrow();
  });
});
