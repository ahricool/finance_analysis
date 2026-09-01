import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from '../Shell.vue';
import { theme } from '@/composables/useTheme';
import { useAuthStore } from '@/stores/authStore';

vi.mock('@/stores/agentChatStore', () => ({ useAgentChatStore: () => false }));

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

async function mountShell(path: string) {
  const router = createTestRouter();
  await router.push(path);
  await router.isReady();
  return { router, wrapper: mount(Shell, { global: { plugins: [router] } }) };
}

describe('Shell navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('keeps account details out of the header and exposes a click user-menu trigger', async () => {
    useAuthStore().currentUser = {
      uid: 1,
      username: 'Alice',
      email: 'alice@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: { gender: 'female' },
    };
    const { wrapper } = await mountShell('/analysis');

    expect(wrapper.get('button[aria-label="打开用户菜单"]')).toBeTruthy();
    expect(wrapper.get('header').text()).not.toContain('alice@example.com');
    expect(wrapper.get('header').text()).not.toContain('退出登录');
  });

  it.each(['/market/watch-list', '/market/holdings', '/market/signals', '/market/signals/123'])(
    'marks market navigation active on %s',
    async (path) => {
      const { wrapper } = await mountShell(path);
      const marketMenu = wrapper.get('button[aria-label="市场"]');
      expect(marketMenu.attributes('aria-current')).toBe('page');
      expect(marketMenu.classes()).toContain('bg-muted');
    },
  );

  it.each([
    '/market/quant/models',
    '/market/quant/signals/NVDA.US',
  ])('marks research navigation active on %s', async (path) => {
    const { wrapper } = await mountShell(path);
    const researchMenu = wrapper.get('button[aria-label="研究"]');
    expect(researchMenu.attributes('aria-current')).toBe('page');
    expect(researchMenu.classes()).toContain('bg-muted');
  });

  it.each(['/tasks', '/tasks/runs'])(
    'marks the task navigation active on %s',
    async (path) => {
      const { wrapper } = await mountShell(path);
      const taskLink = wrapper.get('[data-testid="desktop-main-nav"] a[aria-label="任务"]');
      expect(taskLink.attributes('aria-current')).toBe('page');
      expect(taskLink.classes()).toContain('bg-muted');
    },
  );

  it('toggles dark mode from the keyboard-accessible checkbox menu item', async () => {
    useAuthStore().currentUser = {
      uid: 1,
      username: 'Alice',
      email: 'alice@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: { gender: 'female' },
    };
    theme.value = 'light';
    localStorage.setItem('theme', 'light');
    const { wrapper } = await mountShell('/analysis');

    await wrapper.get('button[aria-label="打开用户菜单"]').trigger('click');
    await vi.waitFor(() => {
      expect(document.body.querySelector('[role="menuitemcheckbox"]')).not.toBeNull();
    });

    const themeItem = document.body.querySelector<HTMLElement>('[role="menuitemcheckbox"]')!;
    themeItem.focus();
    themeItem.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

    await vi.waitFor(() => expect(localStorage.getItem('theme')).toBe('dark'));
    expect(themeItem.getAttribute('aria-checked')).toBe('true');
    wrapper.unmount();
  });

  it('opens the mobile navigation sheet and supports route changes', async () => {
    const { router, wrapper } = await mountShell('/calendar');
    await wrapper.get('button[aria-label="打开主导航"]').trigger('click');

    await vi.waitFor(() => {
      expect(document.body.querySelector('[data-testid="mobile-menu"]')).not.toBeNull();
    });
    const calendarLink = document.body.querySelector<HTMLAnchorElement>(
      '[data-testid="mobile-menu"] a[href="/calendar"]',
    );
    const marketLink = document.body.querySelector<HTMLAnchorElement>(
      '[data-testid="mobile-menu"] a[href="/market/watch-list"]',
    );
    expect(calendarLink?.getAttribute('aria-current')).toBe('page');
    expect(marketLink).not.toBeNull();

    marketLink!.click();
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/market/watch-list'));
    await vi.waitFor(() => {
      expect(document.body.querySelector('[data-testid="mobile-menu"]')).toBeNull();
    });
    wrapper.unmount();
  });
});
