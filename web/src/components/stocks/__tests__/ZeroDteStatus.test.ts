import type { RealtimeQuote } from '@/api/realtimeMarket';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import ZeroDteStatus from '../ZeroDteStatus.vue';

const NOW = new Date('2026-07-22T15:00:00Z');

function quote(): RealtimeQuote {
  return {
    code: 'AAPL',
    market_type: 'US',
    symbol: 'AAPL.US',
    available: true,
    last_price: 101,
    trend_1m: {
      timeframe: '1m',
      target_period: 20,
      effective_period: 20,
      minimum_period: 5,
      state: 'above',
      streak: 3,
      confirmed: true,
    },
    pattern_1m: {
      timeframe: '1m',
      status: 'active',
      signal: {
        timeframe: '1m',
        pattern_type: 'vwap_reclaim_breakdown',
        pattern_name: 'VWAP收复',
        direction: 'bullish_continuation',
        stage: 'confirmed',
        quality_score: 80,
        occurred_at: '2026-07-22T14:40:00Z',
        confirmed_at: '2026-07-22T14:45:00Z',
        trading_date: '2026-07-22',
        bars_ago: 1,
        session_minutes_ago: 1,
        invalidation_price: 100,
        reasons: ['VWAP上方企稳'],
        confirmed: true,
      },
    },
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('ZeroDteStatus', () => {
  it('renders extended status with text, icon, muted direction styling and chase warning', () => {
    const wrapper = mount(ZeroDteStatus, { props: { quote: quote(), marketType: 'US', now: NOW } });
    expect(wrapper.text()).toContain('CALL延续');
    expect(wrapper.text()).toContain('不宜追高');
    expect(wrapper.find('svg').exists()).toBe(true);
    expect(wrapper.get('span.border').classes()).toContain('text-red-500/80');
  });

  it('explains the status without presenting an automatic holding instruction', async () => {
    const wrapper = mount(ZeroDteStatus, {
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
    const wrapper = mount(ZeroDteStatus, { props: { quote: quote(), marketType: 'HK', now: NOW } });
    expect(wrapper.text()).toBe('—');
  });
});
