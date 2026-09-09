import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi, type InstrumentSearchItem } from '@/api/stocks';
import StockAutocomplete from '../StockAutocomplete.vue';

vi.mock('@/api/stocks', () => ({
  stocksApi: {
    parseImport: vi.fn(),
    searchInstruments: vi.fn(),
  },
}));

const moutai: InstrumentSearchItem = {
  code: '600519.SH',
  nativeCode: '600519',
  name: '贵州茅台',
  market: 'CN',
  instrumentType: 'STOCK',
  matchType: 'fuzzy',
};

describe('StockAutocomplete', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      return window.setTimeout(() => callback(performance.now()), 0);
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
    vi.mocked(stocksApi.searchInstruments).mockResolvedValue([moutai]);
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('reruns the current query when the stock index finishes loading', async () => {
    mount(StockAutocomplete, {
      attachTo: document.body,
      props: {
        modelValue: '贵州',
      },
    });

    expect(stocksApi.searchInstruments).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(250);
    await nextTick();
    await vi.advanceTimersByTimeAsync(0);

    expect(stocksApi.searchInstruments).toHaveBeenCalledWith('贵州', expect.objectContaining({ limit: 10 }));
    expect(document.body.textContent).toContain('贵州茅台');
    expect(document.body.textContent).toContain('600519');
  });

  it('positions the teleported suggestion list below the input', async () => {
    const wrapper = mount(StockAutocomplete, {
      attachTo: document.body,
      props: {
        modelValue: '',
      },
    });

    const input = document.querySelector('input[role="combobox"]');
    if (!input) {
      throw new Error('autocomplete input not found');
    }

    vi.spyOn(input, 'getBoundingClientRect').mockReturnValue({
      bottom: 44,
      height: 44,
      left: 24,
      right: 924,
      top: 0,
      width: 900,
      x: 24,
      y: 0,
      toJSON: () => ({}),
    });

    await wrapper.setProps({ modelValue: '贵州' });
    await vi.advanceTimersByTimeAsync(250);
    await nextTick();
    await vi.advanceTimersByTimeAsync(0);

    const list = document.querySelector('#suggestions-list');
    expect(list).not.toBeNull();
    expect((list as HTMLElement).style.top).toBe('44px');
    expect((list as HTMLElement).style.left).toBe('24px');
    expect((list as HTMLElement).style.width).toBe('900px');
  });

  it('emits the matched market when selecting an autocomplete suggestion', async () => {
    const wrapper = mount(StockAutocomplete, {
      attachTo: document.body,
      props: {
        modelValue: '',
      },
    });

    await wrapper.find('input[role="combobox"]').setValue('贵州');
    await vi.advanceTimersByTimeAsync(250);
    await nextTick();
    await vi.advanceTimersByTimeAsync(0);

    const option = document.querySelector('#suggestions-list li');
    expect(option).not.toBeNull();
    await (option as HTMLElement).click();

    expect(wrapper.emitted('submit')?.[0]).toEqual([
      '600519.SH',
      '贵州茅台',
      'autocomplete',
      'CN',
      'stock',
    ]);
  });
});
