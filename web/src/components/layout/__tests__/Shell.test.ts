import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from '../Shell.vue';
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
      const marketLinks = wrapper.findAll('a[aria-label="市场"]');
      expect(marketLinks).toHaveLength(2);
      expect(marketLinks.every((link) => link.attributes('aria-current') === 'page')).toBe(true);
      expect(marketLinks.every((link) => link.classes().includes('text-primary'))).toBe(true);
    },
  );

  it.each([
    ['/market/backtests/123', '回测'],
    ['/market/quant/signals/NVDA.US', '量化'],
  ])('marks only the %s module as %s', async (path, label) => {
    const { wrapper } = await mountShell(path);
    const activeLinks = wrapper.findAll('[data-testid="desktop-main-nav"] a[aria-current="page"]');
    expect(activeLinks).toHaveLength(1);
    expect(activeLinks[0].attributes('aria-label')).toBe(label);
    expect(wrapper.get('button[aria-label="更多"]').attributes('aria-current')).toBe('page');
  });

  it('uses four primary mobile destinations plus a More entry and supports route changes', async () => {
    const { router, wrapper } = await mountShell('/calendar');
    const mobileNav = wrapper.get('[data-testid="mobile-main-nav"]');

    expect(mobileNav.find('.grid-cols-5').exists()).toBe(true);
    expect(mobileNav.findAll('a').map((link) => link.attributes('aria-label'))).toEqual([
      '分析', '日历', '市场', '问股',
    ]);
    expect(mobileNav.get('button[aria-label="更多"]').text()).toContain('更多');
    expect(mobileNav.get('a[aria-label="日历"]').attributes('aria-current')).toBe('page');

    await mobileNav.get('a[aria-label="市场"]').trigger('click');
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/market/watch-list'));
    expect(mobileNav.get('a[aria-label="市场"]').attributes('aria-current')).toBe('page');
  });
});
