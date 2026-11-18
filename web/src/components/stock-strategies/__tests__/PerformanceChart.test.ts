import { mount } from '@vue/test-utils';
import { defineComponent } from 'vue';
import { expect, it } from 'vitest';
import PerformanceChart from '../PerformanceChart.vue';
import type { Metrics } from '@/api/stockStrategies';

it('keeps a manual date range across a curve refresh until a preset is selected', async () => {
  const dates = ['2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17'];
  const items: Metrics[] = dates.map(tradeDate => ({ tradeDate, nav: 100, dailyReturn: 0, totalReturn: 0,
    cagr: null, maxDrawdown: 0, drawdown: 0, exposure: 0, benchmarkReturn: null }));
  const chartStub = defineComponent({
    props: { option: { type: Object, required: true } },
    emits: ['datazoom'],
    methods: { getOption: () => ({ xAxis: [{ data: dates }], dataZoom: [{ startValue: 0, endValue: 1 }] }) },
    template: '<div />',
  });
  const wrapper = mount(PerformanceChart, { props: { items: items.slice(0, 3), benchmark: 'SPY' },
    global: { stubs: { echarts: chartStub } } });
  const chart = wrapper.getComponent(chartStub);
  chart.vm.$emit('datazoom');
  await wrapper.setProps({ items });
  expect(chart.props('option').dataZoom[0]).toMatchObject({ startValue: dates[0], endValue: dates[1] });
  await wrapper.get('button:last-of-type').trigger('click');
  expect(chart.props('option').dataZoom[0]).toMatchObject({ startValue: 0, endValue: 3 });
  wrapper.unmount();
});
