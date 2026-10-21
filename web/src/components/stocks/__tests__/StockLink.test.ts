import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import StockLink from '../StockLink.vue';
import { useStockDetail } from '@/composables/useStockDetail';
import { stocksApi } from '@/api/stocks';
vi.mock('@/api/stocks', () => ({ stocksApi: { searchInstruments: vi.fn().mockResolvedValue([]) } }));
afterEach(() => { useStockDetail().close(); vi.clearAllMocks(); });

describe('stock identity entry', () => {
  it.each(['strong', '.font-mono'])('opens the same market detail from %s and prevents the parent action', async target => {
    const parent = vi.fn();
    const wrapper = mount({ components: { StockLink }, setup: () => ({ parent }), template: '<a href="/research/quant" @click="parent"><StockLink code="AAPL.US" name="Apple" :context="{ tradeDate: \'2026-10-12\', view: \'preview\' }" /></a>' });
    const identity = wrapper.get('button');
    expect(identity.text()).toBe('AAPL.US - Apple');
    expect(identity.get('strong').classes()).toContain('font-bold');
    await wrapper.get(target).trigger('click');
    expect(parent).not.toHaveBeenCalled();
    expect(useStockDetail().selection.value).toEqual({ stock: { code: 'AAPL.US', name: 'Apple', market_type: 'US' }, context: { tradeDate: '2026-10-12', view: 'preview' } });
    expect(stocksApi.searchInstruments).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('delegates to the owning dialog when the caller needs its quote and account context', async () => {
    const select = vi.fn();
    const wrapper = mount(StockLink, { props: { code: '600519.SH', name: '贵州茅台', market: 'CN', onSelect: select } });
    await wrapper.get('button').trigger('click');
    expect(select).toHaveBeenCalledOnce();
    expect(useStockDetail().selection.value).toBeNull();
    wrapper.unmount();
  });
  it('fills absent names from exact master data only and shares simultaneous lookups', async () => {
    vi.mocked(stocksApi.searchInstruments).mockResolvedValueOnce([{ code: 'LOOKUP.US', nativeCode: 'LOOKUP', name: 'Lookup Company', market: 'US', instrumentType: 'stock', matchType: 'exact' }]);
    const wrapper = mount({ components: { StockLink }, template: '<div><StockLink code="LOOKUP.US" /><StockLink code="LOOKUP.US" /></div>' });
    await flushPromises();
    expect(stocksApi.searchInstruments).toHaveBeenCalledOnce();
    expect(wrapper.findAll('strong').map(name => name.text())).toEqual(['Lookup Company', 'Lookup Company']);
    wrapper.unmount();
  });
  it('does not apply a delayed name after changing the stock', async () => {
    let finish!: (items: Awaited<ReturnType<typeof stocksApi.searchInstruments>>) => void;
    vi.mocked(stocksApi.searchInstruments).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(StockLink, { props: { code: 'OLDLOOKUP.US' } });
    await flushPromises();
    await wrapper.setProps({ code: 'MSFT.US', name: 'Microsoft' });
    finish([{ code: 'OLDLOOKUP.US', nativeCode: 'OLDLOOKUP', name: 'Old Company', market: 'US', instrumentType: 'stock', matchType: 'exact' }]);
    await flushPromises();
    expect(wrapper.text()).toBe('MSFT.US - Microsoft');
    wrapper.unmount();
  });
  it('shows explicit missing-name text without substituting a fuzzy search match', async () => {
    vi.mocked(stocksApi.searchInstruments).mockResolvedValueOnce([{ code: 'WRONG.US', nativeCode: 'WRONG', name: 'Other Company', market: 'US', instrumentType: 'stock', matchType: 'fuzzy' }]);
    const wrapper = mount(StockLink, { props: { code: 'MISSINGNAME.US' } });
    await flushPromises();
    expect(wrapper.text()).toBe('MISSINGNAME.US - 名称暂缺');
    await wrapper.get('button').trigger('keydown', { key: 'Enter' });
    await wrapper.get('button').trigger('click');
    expect(useStockDetail().selection.value?.stock.code).toBe('MISSINGNAME.US');
    wrapper.unmount();
  });
});

it('stops row activation keys while preserving Escape dismissal and Tab focus handling', async () => {
  const parent = vi.fn();
  const wrapper = mount({ components: { StockLink }, setup: () => ({ parent }), template: '<div @keydown="parent"><StockLink code="AAPL.US" name="Apple" /></div>' });
  for (const key of ['Enter', ' ']) await wrapper.get('button').trigger('keydown', { key });
  expect(parent).not.toHaveBeenCalled();
  for (const key of ['Escape', 'Tab']) await wrapper.get('button').trigger('keydown', { key });
  expect(parent.mock.calls.map(([event]) => event.key)).toEqual(['Escape', 'Tab']);
  wrapper.unmount();
});
