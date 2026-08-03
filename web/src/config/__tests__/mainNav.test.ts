import { describe, expect, it } from 'vitest';
import { allNavDestinations, mainNavItems } from '../mainNav';

describe('main navigation', () => {
  it('keeps tasks last while keeping market scoped', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual(['分析', '市场', '研究', '日历', '问股', '任务']);
    expect(mainNavItems[0]).toMatchObject({ key: 'analysis', to: '/analysis', exact: true });
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      children: [
        { key: 'watch-list', to: '/market/watch-list' },
        { key: 'holdings', to: '/market/holdings' },
        { key: 'signals', to: '/market/signals' },
      ],
    });
    expect(mainNavItems.find((item) => item.key === 'research')).toMatchObject({
      children: [
        { key: 'backtest', to: '/market/backtests', activePathPrefix: '/market/backtests' },
        { key: 'quant', to: '/market/quant', activePathPrefix: '/market/quant' },
      ],
    });
    expect(allNavDestinations.map((item) => item.key)).toEqual([
      'analysis',
      'watch-list',
      'holdings',
      'signals',
      'backtest',
      'quant',
      'calendar',
      'chat',
      'tasks',
    ]);
    expect(mainNavItems.find((item) => item.key === 'tasks')).toMatchObject({
      label: '任务',
      to: '/tasks',
    });
  });
});
