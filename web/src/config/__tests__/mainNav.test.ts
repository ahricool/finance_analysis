import { describe, expect, it } from 'vitest';
import {
  allNavDestinations,
  mainNavItems,
  marketNavItems,
  researchNavItems,
} from '../mainNav';

describe('main navigation', () => {
  it('orders desktop destinations and scopes research away from market', () => {
    expect(mainNavItems.map((item) => item.label)).toEqual([
      '动态',
      '时间线',
      '研究',
      '市场',
      '加密货币',
      '任务中心',
    ]);
    expect(mainNavItems.map((item) => item.key)).not.toContain('chat');
    expect(mainNavItems.map((item) => item.key)).not.toContain('analysis');
    expect(mainNavItems.some((item) => item.label === '问股' || item.label === 'AI' || item.label === '分析')).toBe(false);
    expect(mainNavItems[0]).toMatchObject({ key: 'dashboard', to: '/dashboard', exact: true });
    expect(mainNavItems.find((item) => item.key === 'timeline')).toMatchObject({ to: '/timeline' });
    expect(mainNavItems.find((item) => item.key === 'research')).toMatchObject({
      to: '/research/etf-rotation',
      activePathPrefix: '/research/',
      children: researchNavItems,
    });
    expect(mainNavItems.find((item) => item.key === 'analysis')).toBeUndefined();
    expect(mainNavItems.find((item) => item.key === 'market')).toMatchObject({
      to: '/market/watch-list',
      activePathPrefix: '/market/',
      children: marketNavItems,
    });
    expect(researchNavItems).toMatchObject([
      { key: 'etf-rotation', to: '/research/etf-rotation' },
      { key: 'trend-following', to: '/research/trend-following' },
      { key: 'industry-strength', label: '行业强度', to: '/research/industry-strength' },
      { key: 'market-sentiment', label: '市场情绪', to: '/research/market-sentiment' },
      { key: 'macro', label: '宏观数据', to: '/research/macro' },
      { key: 'quant', to: '/research/quant', activePathPrefix: '/research/quant' },
    ]);
    expect(allNavDestinations.map((item) => item.key)).toEqual([
      'dashboard',
      'timeline',
      'etf-rotation',
      'trend-following',
      'industry-strength',
      'market-sentiment',
      'macro',
      'quant',
      'watch-list',
      'holdings',
      'crypto-btc',
      'tasks',
    ]);
    expect(mainNavItems.find((item) => item.key === 'tasks')).toMatchObject({
      label: '任务中心',
      to: '/tasks',
    });
  });
});
