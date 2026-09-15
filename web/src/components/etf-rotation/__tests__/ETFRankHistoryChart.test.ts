import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { etfRotationApi } from '@/api/etfRotation';
import { theme } from '@/composables/useTheme';
import type { ETFRankHistoryResponse } from '@/types/etfRotation';
import ETFRankHistoryChart from '../ETFRankHistoryChart.vue';

vi.mock('@/api/etfRotation', () => ({ etfRotationApi: { rankHistory: vi.fn() } }));
vi.mock('vue-echarts', () => ({ default: { name: 'VChart', props: ['option'], template: '<div />' } }));
const history: ETFRankHistoryResponse = {
  market: 'US', dates: ['2026-09-10', '2026-09-11', '2026-09-14'], officialCount: 2,
  previewDate: '2026-09-14', previewTime: null, generatedAt: null,
  series: [
    { code: 'QQQ.US', name: 'Nasdaq', ranks: [7, null, 2] },
    { code: 'SPY.US', name: 'S&P 500', ranks: [1, 2, 4] },
  ],
};
const props = { market: 'US' as const, includePreview: true, refreshKey: 0 };
beforeEach(() => { vi.mocked(etfRotationApi.rankHistory).mockReset().mockResolvedValue(history); });
afterEach(() => { theme.value = 'light'; });

it('plots all ETFs with inverse integer ranks, gaps, plain legend and an explicit preview point', async () => {
  const wrapper = mount(ETFRankHistoryChart, { props });
  await flushPromises();
  const option = wrapper.findComponent({ name: 'VChart' }).props('option');
  expect(option.xAxis.data).toEqual(history.dates);
  expect(option.yAxis).toMatchObject({ inverse: true, min: 1, minInterval: 1, max: 7 });
  expect(option.legend.type).toBe('plain');
  expect(option.series).toHaveLength(2);
  expect(option.series[0]).toMatchObject({
    name: 'Nasdaq', connectNulls: false, smooth: 0.25, symbolSize: 3, lineStyle: { width: 1 },
    emphasis: { focus: 'series', lineStyle: { width: 2 } },
    data: [7, null, { value: 2, symbol: 'emptyCircle', symbolSize: 8 }],
  });
  expect(option.tooltip.formatter({ dataIndex: 2, seriesIndex: 0 })).toBe('2026-09-14 · Preview\nNasdaq / QQQ.US\nRank: #2');
  expect(option.tooltip.formatter({ dataIndex: 0, seriesIndex: 0 })).not.toContain('Preview');
  expect(wrapper.text()).toContain('不计入 30 个正式交易日');
  wrapper.unmount();
});

it('reacts to dark theme and renders empty history', async () => {
  const wrapper = mount(ETFRankHistoryChart, { props });
  await flushPromises();
  const chart = wrapper.findComponent({ name: 'VChart' });
  const color = chart.props('option').yAxis.axisLabel.color;
  theme.value = 'dark';
  await wrapper.vm.$nextTick();
  expect(chart.props('option').yAxis.axisLabel.color).not.toBe(color);
  vi.mocked(etfRotationApi.rankHistory).mockResolvedValue({ ...history, dates: [], series: [], previewDate: null });
  await wrapper.setProps({ refreshKey: 1 });
  await flushPromises();
  expect(wrapper.text()).toContain('暂无排名历史');
  wrapper.unmount();
});

it('handles failure locally and retries', async () => {
  vi.mocked(etfRotationApi.rankHistory).mockRejectedValueOnce(new Error('unavailable'));
  const wrapper = mount(ETFRankHistoryChart, { props });
  await flushPromises();
  const retry = wrapper.findAll('button').find(button => button.text() === '重试排名历史')!;
  expect(retry.exists()).toBe(true);
  await retry.trigger('click');
  await flushPromises();
  expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(true);
  wrapper.unmount();
});

it('ignores a stale market response and passes the selected historical cutoff', async () => {
  let finish!: (value: ETFRankHistoryResponse) => void;
  vi.mocked(etfRotationApi.rankHistory).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const wrapper = mount(ETFRankHistoryChart, { props });
  await wrapper.setProps({ market: 'CN', asOf: '2026-09-11', includePreview: false });
  await flushPromises();
  expect(etfRotationApi.rankHistory).toHaveBeenLastCalledWith('CN', '2026-09-11', false);
  finish({ ...history, series: [] });
  await flushPromises();
  expect(wrapper.findComponent({ name: 'VChart' }).props('option').series).toHaveLength(2);
  wrapper.unmount();
});
