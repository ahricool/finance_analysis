import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TimezoneSwitcher from '../TimezoneSwitcher.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';

describe('TimezoneSwitcher header menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.innerHTML = '';
  });

  it('renders timezone options inside a dropdown menu', async () => {
    const wrapper = mount(TimezoneSwitcher);

    await wrapper.get('button[aria-label="切换展示时区"]').trigger('click');

    await vi.waitFor(() => {
      expect(document.body.querySelector('[role="menu"]')).not.toBeNull();
    });
    const menu = document.body.querySelector<HTMLElement>('[role="menu"]')!;
    expect(menu.textContent).toContain('展示时区');
    expect(menu.textContent).toContain('北京时间');
    expect(menu.textContent).toContain('美东时间');
    wrapper.unmount();
  });

  it('persists the selected timezone through the store', async () => {
    const wrapper = mount(TimezoneSwitcher);
    const store = useTimezoneStore();

    await wrapper.get('button[aria-label="切换展示时区"]').trigger('click');
    await vi.waitFor(() => {
      expect(document.body.querySelectorAll('[role="menuitemradio"]').length).toBe(2);
    });

    const options = document.body.querySelectorAll<HTMLElement>('[role="menuitemradio"]');
    const eastern = Array.from(options).find((option) =>
      option.textContent?.includes('美东时间'),
    )!;
    eastern.focus();
    eastern.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

    await vi.waitFor(() => expect(store.displayTimezone).toBe('America/New_York'));
    expect(localStorage.getItem('display_timezone')).toBe('America/New_York');
    wrapper.unmount();
  });
});
