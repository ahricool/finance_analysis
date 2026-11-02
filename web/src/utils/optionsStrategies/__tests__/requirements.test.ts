import { describe, expect, it } from 'vitest';
import { OPTION_STRATEGIES } from '../catalog';
import { STRATEGY_GROUPS, STRATEGY_REQUIREMENTS, strategyGroup } from '../requirements';

describe('option strategy execution groups', () => {
  it('partitions every structure and keeps only the four option-only buyers in the default group', () => {
    const grouped = Object.fromEntries(STRATEGY_GROUPS.map(group => [group.id,
      OPTION_STRATEGIES.filter(row => strategyGroup(row.setup) === group.id).map(row => row.id)]));
    expect(grouped.buyer).toEqual(['long-call', 'long-put', 'long-straddle', 'long-strangle']);
    expect(grouped.seller).toHaveLength(35);
    expect(grouped.capital).toHaveLength(14);
    expect(Object.values(grouped).flat()).toHaveLength(OPTION_STRATEGIES.length);
    for (const row of OPTION_STRATEGIES) {
      const requirements = STRATEGY_REQUIREMENTS[row.setup];
      expect(requirements).toBeDefined();
      expect(requirements.labels.length).toBeGreaterThan(0);
      if (strategyGroup(row.setup) === 'seller') {
        expect(requirements.sellsOptions).toBe(true);
        expect(requirements.stock).toBe('none');
        expect(requirements.cashReserve).toBe(false);
      }
    }
  });
  it('uses actual legs rather than buy/sell names or limited-risk badges', () => {
    const group = (id: string) => strategyGroup(OPTION_STRATEGIES.find(row => row.id === id)!.setup);
    for (const id of ['bull-call-spread', 'long-call-butterfly', 'long-iron-condor', 'long-ratio-call',
      'long-call-calendar', 'synthetic-long-stock', 'long-box']) expect(group(id)).toBe('seller');
    for (const id of ['cash-backed-call', 'cash-secured-put', 'wheel', 'covered-call', 'covered-put',
      'protective-call', 'protective-put', 'synthetic-long-call', 'synthetic-long-put', 'conversion', 'reversal']) {
      expect(group(id)).toBe('capital');
    }
  });
});
