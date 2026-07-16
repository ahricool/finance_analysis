import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import TrendStatus from '../TrendStatus.vue';
import type { RealtimeTrend } from '@/api/realtimeMarket';

function trend(overrides: Partial<RealtimeTrend> = {}): RealtimeTrend {
  return {
    timeframe: '1m',
    target_period: 20,
    effective_period: 20,
    minimum_period: 5,
    state: 'above',
    streak: 3,
    ma_value: 132.48,
    close: 132.96,
    distance_pct: 0.36,
    bar_time: '2026-07-16T14:31:00Z',
    trading_date: '2026-07-16',
    trade_session: 'regular',
    confirmed: true,
    ...overrides,
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('TrendStatus', () => {
  it.each([
    ['above', 3, '多 3', 'bg-red-500'],
    ['below', 3, '空 3', 'bg-emerald-500'],
    ['above', 1, '多 1', 'bg-amber-500'],
    ['below', 1, '空 1', 'bg-amber-500'],
    ['neutral', 1, '中 1', 'bg-amber-500'],
    ['neutral', 3, '中 3', 'bg-amber-500'],
  ] as const)('renders %s streak %i', (state, streak, label, dotClass) => {
    const wrapper = mount(TrendStatus, { props: { trend: trend({ state, streak }) } });
    expect(wrapper.text()).toContain(label);
    expect(wrapper.get('[data-testid="trend-dot"]').classes()).toContain(dotClass);
  });

  it.each([undefined, null, trend({ state: 'insufficient', streak: 0, confirmed: false })])(
    'renders missing or insufficient data',
    (value) => {
      const wrapper = mount(TrendStatus, { props: { trend: value } });
      expect(wrapper.text()).toContain('数据不足');
      expect(wrapper.get('[data-testid="trend-dot"]').classes()).toContain('bg-muted-text');
    },
  );

  it('explains partial periods and omits invalid optional values', async () => {
    const wrapper = mount(TrendStatus, {
      attachTo: document.body,
      props: {
        trend: trend({
          effective_period: 8,
          ma_value: Number.NaN,
          close: null,
          distance_pct: undefined,
          bar_time: 'not-a-date',
        }),
      },
    });
    await wrapper.get('[tabindex="0"]').trigger('focus');
    const content = document.body.querySelector('[role="tooltip"]')?.textContent ?? '';
    expect(content).toContain('当前周期：8 / 目标周期：20');
    expect(content).not.toContain('NaN');
    expect(content).not.toContain('undefined');
    expect(content).not.toContain('Invalid Date');
  });
});
