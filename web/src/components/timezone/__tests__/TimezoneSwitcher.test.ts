import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import TimezoneSwitcher from '../TimezoneSwitcher.vue';

describe('TimezoneSwitcher settings menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('uses a generic settings trigger and renders timezone controls inside the menu', async () => {
    const wrapper = mount(TimezoneSwitcher);

    await wrapper.get('button[aria-label="打开设置菜单"]').trigger('click');

    expect(wrapper.get('[role="menu"]').attributes('aria-label')).toBe('设置');
    expect(wrapper.text()).toContain('展示时区');
    expect(wrapper.text()).toContain('北京时间');
    expect(wrapper.text()).toContain('美东时间');
  });

  it('keeps the menu open briefly while the pointer moves from trigger to popup', async () => {
    vi.useFakeTimers();
    const wrapper = mount(TimezoneSwitcher);

    await wrapper.trigger('mouseenter');
    expect(wrapper.find('[role="menu"]').exists()).toBe(true);

    await wrapper.trigger('mouseleave');
    expect(wrapper.find('[role="menu"]').exists()).toBe(true);

    vi.advanceTimersByTime(179);
    await nextTick();
    expect(wrapper.find('[role="menu"]').exists()).toBe(true);

    vi.advanceTimersByTime(1);
    await nextTick();
    expect(wrapper.find('[role="menu"]').exists()).toBe(false);
  });
});
