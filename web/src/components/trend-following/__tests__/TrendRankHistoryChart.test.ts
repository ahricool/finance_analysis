import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { theme } from '@/composables/useTheme';
import TrendRankHistoryChart from '../TrendRankHistoryChart.vue';

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'autoresize'], template: '<div />' },
}));

describe('TrendRankHistoryChart', () => {
  afterEach(() => { theme.value = 'light'; });

  it('orders snapshots chronologically without changing the history list and puts better ranks higher', () => {
    const history = [
      { tradeDate: '2026-08-28', rank: 1 },
      { tradeDate: '2026-08-26', rank: 20 },
      { tradeDate: '2026-08-27', rank: 8 },
    ];
    const wrapper = mount(TrendRankHistoryChart, { props: { history } });
    const chart = wrapper.findComponent({ name: 'VChart' });
    const option = chart.props('option');
    expect(option.xAxis.data).toEqual(['2026-08-26', '2026-08-27', '2026-08-28']);
    expect(option.series[0].data).toEqual([20, 8, 1]);
    expect(option.yAxis).toMatchObject({ inverse: true, min: 1, minInterval: 1 });
    expect(history[0]!.tradeDate).toBe('2026-08-28');
    expect(chart.props('autoresize')).toBeDefined();
  });

  it('keeps unranked snapshots as gaps and renders an empty state with no valid ranks', async () => {
    const wrapper = mount(TrendRankHistoryChart, { props: { history: [
      { tradeDate: '2026-08-26', rank: 5 },
      { tradeDate: '2026-08-27', rank: 0 },
      { tradeDate: '2026-08-28', rank: 2 },
    ] } });
    expect(wrapper.findComponent({ name: 'VChart' }).props('option').series[0]).toMatchObject({
      data: [5, null, 2], connectNulls: false,
    });
    await wrapper.setProps({ history: [] });
    expect(wrapper.text()).toContain('暂无排名历史');
    expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(false);
    await wrapper.setProps({ history: [{ tradeDate: '2026-08-28', rank: 0 }] });
    expect(wrapper.text()).toContain('暂无排名历史');
  });

  it('shows a single snapshot as a point and adapts to dark mode', async () => {
    const wrapper = mount(TrendRankHistoryChart, { props: { history: [{ tradeDate: '2026-08-28', rank: 1 }] } });
    const chart = wrapper.findComponent({ name: 'VChart' });
    expect(chart.props('option').series[0]).toMatchObject({ data: [1], showSymbol: true });
    expect(chart.props('option').yAxis.max).toBeGreaterThan(1);
    const lightLabel = chart.props('option').yAxis.axisLabel.color;
    theme.value = 'dark';
    await wrapper.vm.$nextTick();
    expect(chart.props('option').yAxis.axisLabel.color).not.toBe(lightLabel);
    expect(chart.props('option').tooltip.valueFormatter(1)).toBe('第 1 名');
  });
});
