import { describe, expect, it } from 'vitest';
import {
  allNavDestinations,
  mainNavItems,
  marketNavItems,
  researchNavItems,
} from '../mainNav';

describe('main navigation', () => {
  it('keeps tasks last while keeping market scoped', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual(['分析', '市场', '研究', '日历', '问股', '任务']);
    expect(mainNavItems[0]).toMatchObject({ key: 'analysis', to: '/analysis', exact: true });
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      children: marketNavItems,
    });
    expect(mainNavItems.find((item) => item.key === 'research')).toMatchObject({
      to: '/market/quant',
      children: researchNavItems,
    });
    expect(researchNavItems).toMatchObject([
      { key: 'quant', to: '/market/quant', activePathPrefix: '/market/quant' },
      { key: 'etf-rotation', to: '/market/etf-rotation' },
      { key: 'trend-following', to: '/market/trend-following' },
    ]);
    expect(allNavDestinations.map((item) => item.key)).toEqual([
      'analysis',
      'watch-list',
      'holdings',
      'quant',
      'etf-rotation',
      'trend-following',
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
