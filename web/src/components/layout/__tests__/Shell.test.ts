import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from '../Shell.vue';
import { useAuthStore } from '@/stores/authStore';

vi.mock('@/stores/agentChatStore', () => ({
  useAgentChatStore: () => false,
}));

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        component: { template: '<div />' },
      },
      {
        path: '/analysis',
        component: { template: '<div />' },
      },
      {
        path: '/:pathMatch(.*)*',
        component: { template: '<div />' },
      },
    ],
  });
}

describe('Shell user menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('keeps only the avatar visible in the nav and renders user details in the popup', async () => {
    const authStore = useAuthStore();
    authStore.currentUser = {
      uid: 1,
      username: 'Alice',
      email: 'alice@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: {
        gender: 'female',
      },
    };

    const router = createTestRouter();
    await router.push('/');
    await router.isReady();

    const wrapper = mount(Shell, {
      global: {
        plugins: [router],
      },
    });

    const avatarButton = wrapper.get('button[aria-label="查看当前登录用户信息"]');
    expect(avatarButton.text()).toBe('');

    const popup = wrapper.get('[aria-label="当前登录用户"] .absolute');
    expect(popup.classes()).toContain('group-hover:visible');
    expect(popup.text()).toContain('性别');
    expect(popup.text()).toContain('女');
    expect(popup.text()).toContain('角色');
    expect(popup.text()).toContain('女王');
    expect(popup.text()).toContain('邮箱');
    expect(popup.text()).toContain('alice@example.com');
    expect(popup.text().indexOf('性别')).toBeLessThan(popup.text().indexOf('角色'));
    expect(popup.text().indexOf('角色')).toBeLessThan(popup.text().indexOf('邮箱'));
    expect(popup.text().indexOf('邮箱')).toBeLessThan(popup.text().indexOf('个人中心'));
    expect(popup.text().indexOf('个人中心')).toBeLessThan(popup.text().indexOf('任务中心'));
    expect(popup.text().indexOf('任务中心')).toBeLessThan(popup.text().indexOf('退出'));
    expect(popup.find('.lucide-chevron-right').exists()).toBe(true);
    expect(popup.find('a[href="/tasks"]').text()).toContain('任务中心');
    expect(popup.get('button').text()).toBe('退出');
  });

  it.each(['/market/watch-list', '/market/holdings', '/market/signals', '/market/signals/123'])(
    'keeps market navigation active on %s',
    async (path) => {
      const router = createTestRouter();
      await router.push(path);
      await router.isReady();

      const wrapper = mount(Shell, {
        global: {
          plugins: [router],
        },
      });

      const marketLinks = wrapper.findAll('a[aria-label="市场"]');
      expect(marketLinks).toHaveLength(2);
      expect(marketLinks.every((link) => link.classes().includes('text-[hsl(var(--primary))]'))).toBe(true);
      expect(marketLinks.every((link) => link.attributes('aria-current') === 'page')).toBe(true);
      expect(marketLinks.every((link) => link.find('span.absolute').exists())).toBe(true);
    },
  );

  it.each([
    ['/market/backtests/123', '回测'],
    ['/market/quant/signals/NVDA.US', '量化'],
  ])('highlights only %s as %s', async (path, label) => {
    const router = createTestRouter();
    await router.push(path);
    await router.isReady();

    const wrapper = mount(Shell, { global: { plugins: [router] } });
    const activeLinks = wrapper.findAll('a[aria-current="page"]');

    expect(activeLinks).toHaveLength(2);
    expect(activeLinks.every((link) => link.attributes('aria-label') === label)).toBe(true);
    expect(wrapper.findAll('a[aria-label="市场"]').every((link) => !link.attributes('aria-current'))).toBe(true);
  });

  it('shows every core destination in the mobile nav and navigates from calendar to market', async () => {
    const router = createTestRouter();
    await router.push('/calendar');
    await router.isReady();

    const wrapper = mount(Shell, {
      global: {
        plugins: [router],
      },
    });

    const mobileNav = wrapper.get('[data-testid="mobile-main-nav"]');
    expect(mobileNav.find('.grid-cols-6').exists()).toBe(true);
    expect(mobileNav.findAll('a').map((link) => link.attributes('aria-label'))).toEqual([
      '分析',
      '日历',
      '市场',
      '回测',
      '量化',
      '问股',
    ]);
    expect(mobileNav.get('a[aria-label="日历"]').attributes('aria-current')).toBe('page');

    await mobileNav.get('a[aria-label="市场"]').trigger('click');

    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe('/market/watch-list');
    });
    expect(mobileNav.get('a[aria-label="市场"]').attributes('aria-current')).toBe('page');
  });
});
