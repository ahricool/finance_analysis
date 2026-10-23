import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import HeatmapChart from '../HeatmapChart.vue';
import type { HeatmapSnapshot } from '@/api/marketHeatmap';

const snapshot: HeatmapSnapshot = {
  market: 'US', source: 'yfinance', generatedAt: '2026-10-23T14:45:00Z', dataAsOf: null, dataLatestAt: null,
  classificationObservedAt: null, minMarketCap: 2e9, refreshSeconds: 900, excludedCount: 0, unclassifiedCount: 0,
  items: [{ code: 'AAPL.US', name: 'A very long complete company name without an ellipsis', marketCap: 5e12,
    price: 100, changePct: 1.23, groupCode: 'tech', groupName: '科技', quoteTime: null },
  { code: 'JPM.US', name: 'JPMorgan', marketCap: 5e11, price: 100, changePct: null,
    groupCode: 'banks', groupName: '银行', quoteTime: null }],
};
describe('readable heatmap', () => {
  it('renders full names, canonical codes and changes as accessible stock buttons', async () => {
    const wrapper = mount(HeatmapChart, { props: { snapshot } });
    expect(wrapper.findAll('[data-testid="heatmap-stock"]')).toHaveLength(2);
    const apple = wrapper.get('[data-code="AAPL.US"]');
    expect(apple.text()).toContain(snapshot.items[0]!.name);
    expect(apple.text()).toContain('AAPL.US');
    expect(apple.text()).toContain('+1.23%');
    expect(apple.attributes('type')).toBe('button');
    await apple.trigger('click');
    expect(wrapper.emitted('select')).toEqual([[snapshot.items[0]]]);
    expect(wrapper.get('[data-code="JPM.US"]').text()).toContain('涨跌幅暂缺');
    wrapper.unmount();
  });
  it('filters visible industries and stocks without fetching more data', async () => {
    const wrapper = mount(HeatmapChart, { props: { snapshot, groupCode: 'tech' } });
    expect(wrapper.findAll('[data-testid="heatmap-group"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="heatmap-stock"]')).toHaveLength(1);
    await wrapper.setProps({ search: 'missing' });
    expect(wrapper.find('[data-testid="heatmap-stock"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
