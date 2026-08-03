import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TimezoneSwitcher from '../TimezoneSwitcher.vue';

describe('TimezoneSwitcher header menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.innerHTML = '';
  });

  it('uses a dedicated timezone trigger and renders timezone controls inside the menu', async () => {
    const wrapper = mount(TimezoneSwitcher);

    await wrapper.get('button[aria-label="切换展示时区"]').trigger('click');

    await vi.waitFor(() => expect(document.body.querySelector('[role="menu"]')).not.toBeNull());
    const menuText = document.body.querySelector('[role="menu"]')?.textContent;
    expect(menuText).toContain('展示时区');
    expect(menuText).toContain('北京时间');
    expect(menuText).toContain('美东时间');
    wrapper.unmount();
  });

  it('opens on click instead of hover', async () => {
    const wrapper = mount(TimezoneSwitcher);

    await wrapper.trigger('mouseenter');
    expect(document.body.querySelector('[role="menu"]')).toBeNull();

    await wrapper.get('button[aria-label="切换展示时区"]').trigger('click');
    await vi.waitFor(() => expect(document.body.querySelector('[role="menu"]')).not.toBeNull());
    wrapper.unmount();
  });
});
