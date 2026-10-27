import type { RealtimeQuote } from '@/api/realtimeMarket';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import IntradayDirectionStatus from '../IntradayDirectionStatus.vue';

const NOW = new Date('2026-07-22T15:00:00Z');

function quote(): RealtimeQuote {
  return {
    code: 'AAPL',
    marketType: 'US',
    symbol: 'AAPL.US',
    available: true,
    eventTime: NOW.toISOString(),
    receivedAt: NOW.toISOString(),
    lastPrice: 101,
    trend1m: {
      timeframe: '1m',
      targetPeriod: 20,
      effectivePeriod: 20,
      minimumPeriod: 5,
      state: 'above',
      streak: 3,
      confirmed: true,
    },
    pattern1m: {
      timeframe: '1m',
      status: 'active',
      signal: {
        timeframe: '1m',
        patternType: 'vwap_reclaim_breakdown',
        patternName: 'VWAP收复',
        direction: 'bullish_continuation',
        stage: 'confirmed',
        qualityScore: 80,
        occurredAt: '2026-07-22T14:40:00Z',
        confirmedAt: '2026-07-22T14:45:00Z',
        tradingDate: '2026-07-22',
        barsAgo: 1,
        sessionMinutesAgo: 1,
        invalidationPrice: 100,
        reasons: ['VWAP上方企稳'],
        confirmed: true,
      },
    },
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('IntradayDirectionStatus', () => {
  it('renders extended status with text, icon, muted direction styling and chase warning', () => {
    const wrapper = mount(IntradayDirectionStatus, { props: { quote: quote(), marketType: 'US', now: NOW } });
    expect(wrapper.text()).toContain('多头延续');
    expect(wrapper.text()).toContain('不宜追高');
    expect(wrapper.find('svg').exists()).toBe(true);
    expect(wrapper.get('span.border').classes()).toContain('text-market-up/80');
  });

  it('explains the status without presenting an automatic holding instruction', async () => {
    const wrapper = mount(IntradayDirectionStatus, {
      attachTo: document.body,
      props: { quote: quote(), marketType: 'US', now: NOW },
    });
    expect(wrapper.findAll('[data-slot="tooltip-trigger"]')).toHaveLength(1);
    await wrapper.get('[tabindex="0"]').trigger('focus');
    const content = document.body.querySelector('[role="tooltip"]')?.textContent ?? '';
    expect(content).toContain('不宜直接追高');
    expect(content).toContain('不代表自动交易或强制持仓指令');
  });

  it('renders a dash for a non-US instrument', () => {
    const wrapper = mount(IntradayDirectionStatus, { props: { quote: quote(), marketType: 'HK', now: NOW } });
    expect(wrapper.text()).toBe('—');
  });

  it.each([
    ['行情超前', 31_000, undefined, '领先'],
    ['行情延迟', -31_000, undefined, '落后'],
    ['趋势更新延迟', 0, -181_000, '180秒'],
    ['时间异常', null, undefined, '可靠'],
  ] as const)('renders %s with a distinct explanation', async (expected, offset, trendOffset, explanation) => {
    const value = quote();
    value.eventTime = offset === null ? undefined : new Date(NOW.getTime() + offset).toISOString();
    if (trendOffset !== undefined) value.trend1m!.barTime = new Date(NOW.getTime() + trendOffset).toISOString();
    const wrapper = mount(IntradayDirectionStatus, { attachTo: document.body, props: { quote: value, marketType: 'US', now: NOW } });
    expect(wrapper.text()).toBe(expected);
    await wrapper.get('[tabindex="0"]').trigger('focus');
    expect(document.body.querySelector('[role="tooltip"]')?.textContent).toContain(explanation);
    wrapper.unmount();
  });
});
