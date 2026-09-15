import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { trendFollowingApi } from '@/api/trendFollowing';
import { theme } from '@/composables/useTheme';
import type { TrendBreadthResponse, TrendTransitionsResponse } from '@/types/trendFollowing';
import TrendMarketOverview from '../TrendMarketOverview.vue';
import { delta5D } from '../breadthCharts';

vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: { breadthHistory: vi.fn(), transitions: vi.fn() } }));
vi.mock('vue-echarts', () => ({ default: { name: 'VChart', props: ['option', 'autoresize'], template: '<div />' } }));
const history: TrendBreadthResponse = {
  market: 'US', dates: [], officialCount: 6, previewDate: null, previewTime: null, generatedAt: null, warnings: [],
  points: Array.from({ length: 6 }, (_, i) => ({ tradeDate: `2026-09-${String(i * 2 + 1).padStart(2, '0')}`,
    rankableCount: 100, trendBreadth: 0.4 + i * 0.02, participation: 0.5 + i * 0.02,
    deteriorationBreadth: 0.2 - i * 0.01, inactive: 0.3 - i * 0.01, emerging: 0.1,
    healthy: 0.4 + i * 0.02, deteriorating: 0.2 - i * 0.01, coverage: 1, warning: null, isPreview: false })),
};
const transitions: TrendTransitionsResponse = { market: 'US', days: 3, officialCount: 3, previewDate: null, warnings: [], items: [
  { code: 'TEST.US', name: 'Test stock', previousState: 'CANDIDATE', currentState: 'ENTRY',
    previousDate: '2026-09-09', tradeDate: '2026-09-11', previousRank: 18, currentRank: 9, rankDelta: 9,
    alphaScore: 83, fragilityScore: 20, direction: 'strengthening', priority: 0, isPreview: false },
] };
const props = { market: 'US' as const, includePreview: false, refreshKey: 0 };
beforeEach(() => {
  vi.clearAllMocks();
  theme.value = 'light';
  vi.mocked(trendFollowingApi.breadthHistory).mockResolvedValue(history);
  vi.mocked(trendFollowingApi.transitions).mockResolvedValue(transitions);
});
afterEach(() => { theme.value = 'light'; });

it('shows current KPIs and absolute percentage-point deltas over five sessions', async () => {
  const wrapper = mount(TrendMarketOverview, { props });
  await flushPromises();
  expect(wrapper.get('[data-testid="trend-kpi-trendBreadth"]').text()).toContain('50.0%');
  expect(wrapper.get('[data-testid="trend-kpi-trendBreadth"]').text()).toContain('+10.0pp');
  expect(wrapper.get('[data-testid="trend-kpi-participation"]').text()).toContain('60.0%');
  expect(wrapper.get('[data-testid="trend-kpi-deteriorationBreadth"]').text()).toContain('-5.0pp');
  expect(delta5D(history.points.slice(-5), 'trendBreadth')).toBe('—');
  expect(delta5D([{ ...history.points[0]!, trendBreadth: null }, ...history.points.slice(1)], 'trendBreadth')).toBe('—');
  const charts = wrapper.findAllComponents({ name: 'VChart' });
  const line = charts[0]!.props('option');
  expect(line.series).toHaveLength(2);
  expect(line.yAxis).toMatchObject({ min: 0, max: 100 });
  expect(line.xAxis.data[0]).toBe('2026-09-01');
  const area = charts[1]!.props('option');
  expect(area.series).toHaveLength(4);
  expect(area.legend.selectedMode).toBe(false);
  expect(area.series.every((series: { stack: string }) => series.stack === 'structure')).toBe(true);
  expect(area.series.reduce((sum: number, series: { data: { value: number }[] }) => sum + series.data[0]!.value, 0)).toBeCloseTo(100);
  expect(area.color[2]).toBe(line.color[0]);
  theme.value = 'dark';
  await flushPromises();
  expect(charts[0]!.props('option').tooltip.textStyle.color).toBe('#fafafa');
  wrapper.unmount();
});

it('defaults to 3D, sends direction and range filters, and opens point-in-time detail', async () => {
  const wrapper = mount(TrendMarketOverview, { props });
  await flushPromises();
  expect(trendFollowingApi.transitions).toHaveBeenLastCalledWith('US', 3, 'all', undefined, false);
  const click = async (label: string) => {
    await wrapper.findAll('button').find(button => button.text() === label)!.trigger('click');
    await flushPromises();
  };
  await click('转弱');
  await click('5D');
  expect(trendFollowingApi.transitions).toHaveBeenLastCalledWith('US', 5, 'deteriorating', undefined, false);
  await click('转强');
  await click('1D');
  expect(trendFollowingApi.transitions).toHaveBeenLastCalledWith('US', 1, 'strengthening', undefined, false);
  await wrapper.get('[data-testid="trend-transition"]').trigger('click');
  expect(wrapper.emitted('select')).toEqual([[{ code: 'TEST.US', tradeDate: '2026-09-11', preview: false }]]);
  expect(wrapper.text()).toContain('Rank #18 → #9');
  wrapper.unmount();
});

it('labels Preview points and transitions and preserves official point count', async () => {
  vi.mocked(trendFollowingApi.breadthHistory).mockResolvedValue({ ...history, previewDate: '2026-09-14',
    points: [...history.points, { ...history.points[5]!, tradeDate: '2026-09-14', isPreview: true }] });
  vi.mocked(trendFollowingApi.transitions).mockResolvedValue({ ...transitions, previewDate: '2026-09-14',
    items: [{ ...transitions.items[0]!, tradeDate: '2026-09-14', isPreview: true }] });
  const wrapper = mount(TrendMarketOverview, { props: { ...props, includePreview: true } });
  await flushPromises();
  const option = wrapper.findComponent({ name: 'VChart' }).props('option');
  expect(option.xAxis.data.at(-1)).toBe('2026-09-14 · Preview');
  expect(option.series[0].data.at(-1).symbol).toBe('emptyCircle');
  expect(wrapper.text()).toContain('6 个正式 session + 1 Preview');
  expect(wrapper.get('[data-testid="trend-transition"]').text()).toContain('Preview');
  await wrapper.get('[data-testid="trend-transition"]').trigger('click');
  expect(wrapper.emitted('select')![0]).toEqual([{ code: 'TEST.US', tradeDate: '2026-09-14', preview: true }]);
  wrapper.unmount();
});

it('reloads market, historical cutoff, mode and refresh; stale responses cannot win', async () => {
  let resolve!: (value: TrendBreadthResponse) => void;
  vi.mocked(trendFollowingApi.breadthHistory).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const wrapper = mount(TrendMarketOverview, { props });
  await wrapper.setProps({ market: 'CN', asOf: '2026-09-11' });
  await flushPromises();
  resolve({ ...history, points: [] });
  await flushPromises();
  expect(wrapper.findAllComponents({ name: 'VChart' })).toHaveLength(2);
  expect(trendFollowingApi.breadthHistory).toHaveBeenLastCalledWith('CN', '2026-09-11', false);
  await wrapper.setProps({ includePreview: true, asOf: undefined });
  await flushPromises();
  expect(trendFollowingApi.transitions).toHaveBeenLastCalledWith('CN', 3, 'all', undefined, true);
  await wrapper.setProps({ refreshKey: 1 });
  await flushPromises();
  expect(trendFollowingApi.breadthHistory).toHaveBeenCalledTimes(4);
  wrapper.unmount();
});

it('isolates breadth and transitions failures with retry and empty states', async () => {
  vi.mocked(trendFollowingApi.breadthHistory).mockRejectedValueOnce(new Error('unavailable'));
  const wrapper = mount(TrendMarketOverview, { props });
  await flushPromises();
  expect(wrapper.find('[data-testid="trend-transition"]').exists()).toBe(true);
  await wrapper.findAll('button').find(button => button.text() === '重试趋势广度')!.trigger('click');
  await flushPromises();
  expect(wrapper.findAllComponents({ name: 'VChart' })).toHaveLength(2);
  vi.mocked(trendFollowingApi.transitions).mockRejectedValueOnce(new Error('unavailable'));
  await wrapper.setProps({ refreshKey: 1 });
  await flushPromises();
  expect(wrapper.text()).toContain('重试状态变化');
  expect(wrapper.findAllComponents({ name: 'VChart' })).toHaveLength(2);
  vi.mocked(trendFollowingApi.breadthHistory).mockResolvedValue({ ...history, points: [] });
  vi.mocked(trendFollowingApi.transitions).mockResolvedValue({ ...transitions, items: [] });
  await wrapper.setProps({ refreshKey: 2 });
  await flushPromises();
  expect(wrapper.text()).toContain('暂无趋势广度历史');
  expect(wrapper.text()).toContain('所选范围暂无重要状态变化');
  wrapper.unmount();
});

it('shows incomplete coverage without rescaling state structure', async () => {
  vi.mocked(trendFollowingApi.breadthHistory).mockResolvedValue({ ...history, points: [{ ...history.points[0]!,
    inactive: 0.1, coverage: 0.8, warning: 'State coverage 80/100，占比未归一化。' }] });
  const wrapper = mount(TrendMarketOverview, { props });
  await flushPromises();
  expect(wrapper.text()).toContain('80.0%');
  expect(wrapper.text()).toContain('State coverage 80/100');
  const structure = wrapper.findAllComponents({ name: 'VChart' })[1]!.props('option');
  expect(structure.series.reduce((sum: number, series: { data: { value: number }[] }) => sum + series.data[0]!.value, 0)).toBeCloseTo(80);
  wrapper.unmount();
});
