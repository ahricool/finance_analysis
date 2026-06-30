import { describe, expect, it } from 'vitest';
import { mainNavItems } from '../mainNav';

describe('main navigation', () => {
  it('combines watch list and holdings into one market entry', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual(['首页', '日历', '市场', '问股']);
    expect(mainNavItems.some((item) => item.label === '自选股')).toBe(false);
    expect(mainNavItems.some((item) => item.label === '持仓股')).toBe(false);
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      activePathPrefix: '/market/',
    });
  });
});
