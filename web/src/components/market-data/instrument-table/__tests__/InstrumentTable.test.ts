import { mount, type DOMWrapper } from '@vue/test-utils';
import { afterEach, expect, it } from 'vitest';
import InstrumentRow from '../InstrumentRow.vue';
import InstrumentTable from '../InstrumentTable.vue';
import { tableChartPeriod } from '../state';
import StockLink from '@/components/stocks/StockLink.vue';
import { useStockDetail } from '@/composables/useStockDetail';

afterEach(() => { tableChartPeriod.value = '1m'; useStockDetail().close(); });

it('keeps expansion local to each table while synchronizing chart periods across tables', async () => {
  const wrapper = mount({
    components: { InstrumentRow, InstrumentTable, StockLink },
    template: `<div><section v-for="section in ['positions','ranking']" :key="section">
      <InstrumentTable><tbody><InstrumentRow v-for="id in [1,2]" :key="id" symbol="SPY.US" :row-id="id">
        <td><StockLink code="SPY.US" name="SPDR S&amp;P 500 ETF" /></td>
        <template #chart="{period}"><output>{{ period }}</output></template>
      </InstrumentRow></tbody></InstrumentTable></section></div>`,
  }, { global: { stubs: { LazyChartPanel: { template: '<div><slot /></div>' } } } });
  const [left, right] = wrapper.findAll('section');
  const button = (section: DOMWrapper<Element>, label: string) => section.findAll('button').find(b => b.text() === label)!;
  await button(left!, '全部展开').trigger('click');
  expect(left!.findAll('output').map(o => o.text())).toEqual(['1m', '1m']);
  expect(right!.find('output').exists()).toBe(false);
  await right!.get('tbody tr').trigger('click');
  await button(left!, '日').trigger('click');
  expect(wrapper.findAll('output').map(o => o.text())).toEqual(['1d', '1d', '1d']);
  await right!.get('tbody button').trigger('click');
  expect(useStockDetail().selection.value?.stock.code).toBe('SPY.US');
  expect(right!.get('tbody tr').attributes('aria-expanded')).toBe('true');
  await left!.get('tbody tr').trigger('click');
  expect(left!.findAll('output')).toHaveLength(1);
  await button(right!, '年').trigger('click');
  expect(wrapper.findAll('[data-testid="instrument-chart-row"]').map(row => row.text())).toEqual(['无数据', '无数据']);
  await button(left!, '全部收起').trigger('click');
  expect(left!.find('[data-testid="instrument-chart-row"]').exists()).toBe(false);
  expect(right!.get('tbody tr').attributes('aria-expanded')).toBe('true');
  wrapper.unmount();
});
