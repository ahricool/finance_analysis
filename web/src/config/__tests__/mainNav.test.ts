import { describe, expect, it } from 'vitest';
import { mainNavItems } from '../mainNav';

describe('main navigation', () => {
  it('promotes backtest and quant before chat while keeping market scoped', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual(['分析', '日历', '市场', '回测', '量化', '问股']);
    expect(mainNavItems[0]).toMatchObject({ key: 'analysis', to: '/analysis', exact: true });
    expect(mainNavItems.some((item) => item.label === '自选股')).toBe(false);
    expect(mainNavItems.some((item) => item.label === '持仓股')).toBe(false);
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      activePaths: ['/market/watch-list', '/market/holdings', '/market/signals'],
    });
    expect(mainNavItems.find((item) => item.key === 'backtest')).toMatchObject({
      to: '/market/backtests',
      activePathPrefix: '/market/backtests',
    });
    expect(mainNavItems.find((item) => item.key === 'quant')).toMatchObject({
      to: '/market/quant',
      activePathPrefix: '/market/quant',
    });
  });
});
