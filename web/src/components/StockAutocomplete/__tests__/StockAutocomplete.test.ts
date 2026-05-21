import { mount } from '@vue/test-utils';
import { computed, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StockIndexItem } from '@/types/stockIndex';
import StockAutocomplete from '../StockAutocomplete.vue';

const stockIndexState = vi.hoisted(() => ({
  index: undefined as unknown,
  loading: undefined as unknown,
  fallback: undefined as unknown,
  error: undefined as unknown,
}));

vi.mock('@/composables/useStockIndex', () => ({
  useStockIndex: () => ({
    index: stockIndexState.index,
    loading: stockIndexState.loading,
    fallback: stockIndexState.fallback,
    error: stockIndexState.error,
    loaded: computed(() => !(stockIndexState.loading as ReturnType<typeof ref<boolean>>).value),
  }),
}));

const moutai: StockIndexItem = {
  canonicalCode: '600519.SH',
  displayCode: '600519',
  nameZh: '贵州茅台',
  pinyinFull: 'guizhoumaotai',
  pinyinAbbr: 'gzmt',
  aliases: ['茅台'],
  market: 'CN',
  assetType: 'stock',
  active: true,
  popularity: 100,
};

describe('StockAutocomplete', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      return window.setTimeout(() => callback(performance.now()), 0);
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));

    stockIndexState.index = ref<StockIndexItem[]>([]);
    stockIndexState.loading = ref(true);
    stockIndexState.fallback = ref(false);
    stockIndexState.error = ref<Error | null>(null);
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

    await vi.advanceTimersByTimeAsync(250);
    expect(document.body.textContent).not.toContain('贵州茅台');

    (stockIndexState.index as ReturnType<typeof ref<StockIndexItem[]>>).value = [moutai];
    (stockIndexState.loading as ReturnType<typeof ref<boolean>>).value = false;

    await nextTick();
    await vi.advanceTimersByTimeAsync(250);
    await nextTick();
    await vi.advanceTimersByTimeAsync(0);

    expect(document.body.textContent).toContain('贵州茅台');
    expect(document.body.textContent).toContain('600519');
  });

  it('positions the teleported suggestion list below the input', async () => {
    stockIndexState.index = ref<StockIndexItem[]>([moutai]);
    stockIndexState.loading = ref(false);

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
});
