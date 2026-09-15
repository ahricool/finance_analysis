import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { trendFollowingApi } from '@/api/trendFollowing';
import { theme, systemPrefersDark } from '@/composables/useTheme';
import type { TrendStateHistoryResponse } from '@/types/trendFollowing';
import TrendStateHeatmap from '../TrendStateHeatmap.vue';
import { HEATMAP_STATES, STATE_COLORS, stateTooltip } from '../stateHeatmap';

const dispatch = vi.hoisted(() => vi.fn());
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: { stateHistory: vi.fn() } }));
vi.mock('vue-echarts', () => ({ default: {
  name: 'VChart', props: ['option'], emits: ['click', 'mouseover', 'mouseout'],
  methods: { dispatchAction: dispatch }, template: '<div />',
} }));
const dates = Array.from({ length: 30 }, (_, i) => `2026-08-${String(i + 1).padStart(2, '0')}`);
const history: TrendStateHistoryResponse = {
  market: 'US', anchorDate: dates[29]!, dates, officialCount: 30,
  previewDate: null, previewTime: null, generatedAt: null, warnings: [],
  items: Array.from({ length: 50 }, (_, i) => ({
    code: `S${50 - i}.US`, name: `Stock ${i}`, currentRank: i + 1,
    history: dates.map((_, x) => x === 3 ? null : ({
      rank: 50 - i, state: HEATMAP_STATES[x % HEATMAP_STATES.length]!, alphaScore: 86.3,
      trendScore: 82.6, rsScore: 79.4, fragilityScore: 18.5, trendDurationDays: 14,
    })),
  })),
};
const props = { market: 'US' as const, includePreview: false, refreshKey: 0 };
beforeEach(() => { dispatch.mockClear(); vi.mocked(trendFollowingApi.stateHistory).mockReset().mockResolvedValue(history); });
afterEach(() => { theme.value = 'light'; systemPrefersDark.value = false; });

it('renders 50 × 30 categorical cells with anchored order and scrollable rows', async () => {
  const wrapper = mount(TrendStateHeatmap, { props });
  await flushPromises();
  const option = wrapper.findComponent({ name: 'VChart' }).props('option');
  expect(option.series[0].type).toBe('heatmap');
  expect(option.series[0].data).toHaveLength(1500);
  expect(option.series[0].data[3].value).toEqual([3, 0, -1]);
  expect(option.yAxis.data).toEqual(history.items.map(stock => stock.code));
  expect(option.yAxis.inverse).toBe(true);
  expect(option.yAxis.axisLabel.formatter('S50.US', 0)).toBe('#1 S50.US Stock 0');
  // ECharts restarts the label index at 0 after dataZoom; identify labels by code.
  expect(option.yAxis.axisLabel.formatter('S1.US', 0)).toBe('#50 S1.US Stock 49');
  expect(option.dataZoom[1]).toMatchObject({ type: 'inside', yAxisIndex: 0, moveOnMouseWheel: true, zoomOnMouseWheel: false, minValueSpan: 19, maxValueSpan: 19 });
  expect(option.visualMap.pieces.slice(1)).toEqual(HEATMAP_STATES.map((state, value) => ({ value, color: STATE_COLORS[state].light })));
  expect(HEATMAP_STATES).toEqual(['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN']);
  wrapper.unmount();
});

it('shows stored metrics, missing cells and the preview date in the tooltip', async () => {
  const preview = { ...history, previewDate: dates[29]! };
  vi.mocked(trendFollowingApi.stateHistory).mockResolvedValue(preview);
  const wrapper = mount(TrendStateHeatmap, { props });
  await flushPromises();
  const option = wrapper.findComponent({ name: 'VChart' }).props('option');
  const tooltip = option.tooltip.formatter({ dataIndex: 29 });
  for (const text of ['2026-08-30 · Preview', 'S50.US / Stock 0', 'Rank: #50', 'State: BROKEN',
    'Alpha Score: 86.3', 'Trend Score: 82.6', 'RS Score: 79.4', 'Fragility: 18.5', '持续天数: 14']) expect(tooltip).toContain(text);
  expect(stateTooltip(preview, 3, 0)).toContain('暂无 Snapshot');
  expect(option.xAxis.axisLabel.formatter(dates[29])).toBe('08/30 P');
  expect(option.series[0].data[29].itemStyle.borderWidth).toBe(2);
  expect(wrapper.text()).toContain('不计入 30 个正式交易日');
  wrapper.unmount();
});

it('uses the resolved system theme for cells, labels and tooltip', async () => {
  theme.value = 'system';
  const wrapper = mount(TrendStateHeatmap, { props });
  await flushPromises();
  const chart = wrapper.findComponent({ name: 'VChart' });
  const old = chart.props('option').tooltip.backgroundColor;
  systemPrefersDark.value = true;
  await wrapper.vm.$nextTick();
  expect(chart.props('option').tooltip.backgroundColor).not.toBe(old);
  expect(chart.props('option').visualMap.pieces[1].color).toBe(STATE_COLORS.IDLE.dark);
  wrapper.unmount();
});

it('highlights one complete row and opens the anchor detail from cells and stock names', async () => {
  const wrapper = mount(TrendStateHeatmap, { props });
  await flushPromises();
  const chart = wrapper.findComponent({ name: 'VChart' });
  chart.vm.$emit('mouseover', { componentType: 'series', dataIndex: 35 });
  expect(dispatch).toHaveBeenLastCalledWith({ type: 'highlight', seriesIndex: 0, dataIndex: Array.from({ length: 30 }, (_, i) => i + 30) });
  chart.vm.$emit('click', { componentType: 'series', dataIndex: 35 });
  chart.vm.$emit('click', { componentType: 'yAxis', value: 'S49.US' });
  expect(wrapper.emitted('select')).toEqual(Array(2).fill([{ code: 'S49.US', tradeDate: dates[29], preview: false }]));
  wrapper.unmount();
});

it('reloads for market, date and official/preview mode and discards stale responses', async () => {
  let resolve!: (value: TrendStateHistoryResponse) => void;
  vi.mocked(trendFollowingApi.stateHistory).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const wrapper = mount(TrendStateHeatmap, { props });
  await wrapper.setProps({ market: 'CN', asOf: '2026-08-20' });
  await flushPromises();
  expect(trendFollowingApi.stateHistory).toHaveBeenLastCalledWith('CN', '2026-08-20', false);
  resolve({ ...history, items: [] });
  await flushPromises();
  expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(true);
  await wrapper.setProps({ includePreview: true, asOf: undefined });
  await flushPromises();
  expect(trendFollowingApi.stateHistory).toHaveBeenLastCalledWith('CN', undefined, true);
  wrapper.unmount();
});

it('isolates errors with a retry and handles an empty response', async () => {
  vi.mocked(trendFollowingApi.stateHistory).mockRejectedValueOnce(new Error('unavailable'));
  const wrapper = mount(TrendStateHeatmap, { props });
  await flushPromises();
  expect(wrapper.text()).toContain('状态历史加载失败');
  vi.mocked(trendFollowingApi.stateHistory).mockResolvedValue({ ...history, items: [], dates: [] });
  await wrapper.findAll('button').find(button => button.text() === '重试状态历史')!.trigger('click');
  await flushPromises();
  expect(wrapper.text()).toContain('暂无状态历史');
  wrapper.unmount();
});
