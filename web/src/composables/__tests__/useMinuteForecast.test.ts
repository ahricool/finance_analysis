import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import { fetchMinuteForecast } from '@/api/minuteForecast';
import { useMinuteForecast } from '../useMinuteForecast';

vi.mock('@/api/minuteForecast', () => ({ fetchMinuteForecast: vi.fn() }));

it('observes shared settings toggled while the chart stays mounted', async () => {
  vi.useFakeTimers();
  const response = (enabled: boolean) => ({ enabled, forecast: null, comparison: null });
  vi.mocked(fetchMinuteForecast)
    .mockResolvedValueOnce(response(false))
    .mockResolvedValueOnce(response(true))
    .mockResolvedValueOnce(response(false));
  const wrapper = mount(defineComponent({
    setup() {
      const result = useMinuteForecast(() => 'QQQ.US', () => true);
      return () => h('span', String(result.value?.enabled));
    },
  }));
  try {
    await flushPromises();
    expect(wrapper.text()).toBe('false');
    await vi.advanceTimersByTimeAsync(8_000);
    expect(wrapper.text()).toBe('true');
    await vi.advanceTimersByTimeAsync(8_000);
    expect(wrapper.text()).toBe('false');
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(8_000);
    expect(fetchMinuteForecast).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});
