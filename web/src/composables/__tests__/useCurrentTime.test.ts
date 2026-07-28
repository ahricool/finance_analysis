import { useCurrentTime } from '@/composables/useCurrentTime';
import { mount } from '@vue/test-utils';
import { defineComponent, nextTick } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.useRealTimers();
});

describe('useCurrentTime', () => {
  it('refreshes on one low-frequency timer and clears it on unmount', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-22T14:36:00Z'));
    const clearInterval = vi.spyOn(window, 'clearInterval');

    const wrapper = mount(defineComponent({
      setup() {
        return { now: useCurrentTime() };
      },
      template: '<time>{{ now.toISOString() }}</time>',
    }));

    expect(wrapper.text()).toBe('2026-07-22T14:36:00.000Z');
    vi.advanceTimersByTime(60_000);
    await nextTick();
    expect(wrapper.text()).toBe('2026-07-22T14:37:00.000Z');

    wrapper.unmount();
    expect(clearInterval).toHaveBeenCalledTimes(1);
    clearInterval.mockRestore();
  });
});
