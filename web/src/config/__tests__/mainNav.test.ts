import { describe, expect, it } from 'vitest';
import { mainNavItems } from '../mainNav';

describe('main navigation', () => {
  it('groups market and research destinations and keeps tasks last', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual(['分析', '市场', '研究', '日历', '问股', '任务']);
    expect(mainNavItems[0]).toMatchObject({ key: 'analysis', to: '/analysis', exact: true });
    expect(mainNavItems.some((item) => item.label === '自选股')).toBe(false);
    expect(mainNavItems.some((item) => item.label === '持仓股')).toBe(false);
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      activePaths: ['/market/watch-list', '/market/holdings', '/market/signals'],
    });
    expect(mainNavItems.find((item) => item.key === 'research')).toMatchObject({
      to: '/market/backtests',
      activePaths: ['/market/backtests', '/market/quant'],
    });
    expect(mainNavItems.find((item) => item.key === 'tasks')).toMatchObject({
      label: '任务',
      to: '/tasks',
    });
  });
});
