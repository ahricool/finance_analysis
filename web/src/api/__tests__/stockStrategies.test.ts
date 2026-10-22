import { describe, expect, it } from 'vitest';
import { adapt } from '../stockStrategies';

describe('stock strategy API', () => {
  it('converts contract fields while preserving canonical security dictionary keys', () => {
    const result = adapt<{ payload: { positions: Record<string, { entryPrice: number }>; plan: { exits: Record<string, string[]> } } }>({
      payload: { positions: { 'AAPL.US': { entry_price: 100 }, '600519.SH': { entry_price: 200 } },
        plan: { exits: { 'AAPL.US': ['MA20'] } } },
    });
    expect(result.payload.positions['AAPL.US']?.entryPrice).toBe(100);
    expect(result.payload.positions['600519.SH']?.entryPrice).toBe(200);
    expect(result.payload.plan.exits['AAPL.US']).toEqual(['MA20']);
  });
});
