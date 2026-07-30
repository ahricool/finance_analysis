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
      const marketLink = wrapper.get('[data-testid="desktop-main-nav"] a[aria-label="市场"]');
      expect(marketLink.attributes('aria-current')).toBe('page');
      expect(marketLink.classes()).toContain('bg-muted');
    },
  );

  it.each([
    '/market/backtests',
    '/market/backtests/123',
    '/market/quant/models',
    '/market/quant/signals/NVDA.US',
  ])('marks only the research module active on %s', async (path) => {
    const { wrapper } = await mountShell(path);
    const activeLinks = wrapper.findAll('[data-testid="desktop-main-nav"] a[aria-current="page"]');
    expect(activeLinks).toHaveLength(1);
    expect(activeLinks[0].attributes('aria-label')).toBe('研究');
  });

  it.each(['/tasks', '/tasks/runs'])('marks the tasks entry active on %s', async (path) => {
    const { wrapper } = await mountShell(path);
    const activeLinks = wrapper.findAll('[data-testid="desktop-main-nav"] a[aria-current="page"]');
    expect(activeLinks).toHaveLength(1);
    expect(activeLinks[0].attributes('aria-label')).toBe('任务');
  });

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

  it('opens the mobile navigation sheet with all destinations and closes it on navigation', async () => {
    const { router, wrapper } = await mountShell('/calendar');

    await wrapper.get('[data-testid="mobile-nav-trigger"]').trigger('click');

    await vi.waitFor(() => {
      expect(document.body.querySelector('[data-testid="mobile-main-nav"]')).not.toBeNull();
    });

    const mobileNav = document.body.querySelector<HTMLElement>('[data-testid="mobile-main-nav"]')!;
    const labels = Array.from(mobileNav.querySelectorAll('a')).map((link) =>
      link.getAttribute('aria-label'),
    );
    expect(labels.slice(0, 6)).toEqual(['分析', '市场', '研究', '日历', '问股', '任务']);
    expect(mobileNav.textContent).toContain('个人中心');
    expect(
      mobileNav.querySelector('a[aria-label="日历"]')?.getAttribute('aria-current'),
    ).toBe('page');

    mobileNav
      .querySelector<HTMLAnchorElement>('a[aria-label="市场"]')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/market/watch-list'));
    await vi.waitFor(() => {
      expect(document.body.querySelector('[data-testid="mobile-main-nav"]')).toBeNull();
    });
    wrapper.unmount();
  });
});
