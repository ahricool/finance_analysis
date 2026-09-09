import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from '@/components/layout/Shell.vue';
import { useAuthStore } from '@/stores/authStore';

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/analysis', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  });
}

describe('TimezoneSwitcher header menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.innerHTML = '';
    useAuthStore().currentUser = {
      uid: 1,
      username: 'Alice',
      email: 'alice@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: { gender: 'female' },
    };
  });

  it('uses a dedicated timezone trigger and renders timezone controls inside the menu', async () => {
    const router = createTestRouter();
    await router.push('/analysis');
    await router.isReady();
    const wrapper = mount(Shell, { global: { plugins: [router] } });

    expect(wrapper.find('button[aria-label="切换展示时区"]').exists()).toBe(false);

    await wrapper.get('button[aria-label="打开用户菜单"]').trigger('click');
    await vi.waitFor(() => expect(document.body.querySelector('[data-testid="timezone-menu"]')).not.toBeNull());
    const trigger = document.body.querySelector<HTMLElement>('[data-testid="timezone-menu"]');
    trigger?.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    trigger?.click();
    await vi.waitFor(() => expect(document.body.querySelector('[data-testid="timezone-preference"]')).not.toBeNull());

    const menuText = document.body.textContent;
    expect(menuText).toContain('时区');
    expect(menuText).toContain('北京时间');
    expect(menuText).toContain('美东时间');
    wrapper.unmount();
  });

  it('opens on click instead of hover', async () => {
    const router = createTestRouter();
    await router.push('/analysis');
    await router.isReady();
    const wrapper = mount(Shell, { global: { plugins: [router] } });

    await wrapper.trigger('mouseenter');
    expect(document.body.querySelector('[role="menu"]')).toBeNull();

    await wrapper.get('button[aria-label="打开用户菜单"]').trigger('click');
    await vi.waitFor(() => expect(document.body.querySelector('[role="menu"]')).not.toBeNull());
    wrapper.unmount();
  });
});
