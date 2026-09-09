import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from '../Shell.vue';
import { theme, systemPrefersDark } from '@/composables/useTheme';
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

async function mountShell(path: string) {
  const router = createTestRouter();
  await router.push(path);
  await router.isReady();
  return { router, wrapper: mount(Shell, { global: { plugins: [router] } }) };
}

async function openThemePreference(wrapper: Awaited<ReturnType<typeof mountShell>>['wrapper']) {
  await wrapper.get('button[aria-label="打开用户菜单"]').trigger('click');
  await vi.waitFor(() => {
    expect(document.body.querySelector('[data-testid="theme-menu"]')).not.toBeNull();
  });
  const trigger = document.body.querySelector<HTMLElement>('[data-testid="theme-menu"]');
  trigger?.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
  trigger?.click();
  await vi.waitFor(() => {
    expect(document.body.querySelector('[data-testid="theme-preference"]')).not.toBeNull();
  });
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
    expect(wrapper.find('button[aria-label="切换展示时区"]').exists()).toBe(false);
    expect(wrapper.get('header').text()).not.toContain('alice@example.com');
    expect(wrapper.get('header').text()).not.toContain('退出登录');
  });

  it.each(['/market/watch-list', '/market/holdings'])(
    'marks market navigation active on %s',
    async (path) => {
      const { wrapper } = await mountShell(path);
      const marketMenu = wrapper.get('button[aria-label="市场"]');
      expect(marketMenu.attributes('aria-current')).toBe('page');
      expect(marketMenu.classes()).toContain('bg-muted');
      expect(wrapper.get('button[aria-label="研究"]').attributes('aria-current')).toBeUndefined();
    },
  );

  it.each([
    '/research/quant/models',
    '/research/quant/signals/NVDA.US',
    '/research/etf-rotation',
  ])('marks research navigation active on %s', async (path) => {
    const { wrapper } = await mountShell(path);
    const researchMenu = wrapper.get('button[aria-label="研究"]');
    expect(researchMenu.attributes('aria-current')).toBe('page');
    expect(researchMenu.classes()).toContain('bg-muted');
    expect(wrapper.get('button[aria-label="市场"]').attributes('aria-current')).toBeUndefined();
    expect(wrapper.find('[data-testid="desktop-main-nav"] a[aria-label="分析"]').attributes('aria-current')).toBeUndefined();
  });

  it.each(['/tasks', '/tasks/runs'])(
    'marks the task navigation active on %s',
    async (path) => {
      const { wrapper } = await mountShell(path);
      const taskLink = wrapper.get('[data-testid="desktop-main-nav"] a[aria-label="任务中心"]');
      expect(taskLink.attributes('aria-current')).toBe('page');
      expect(taskLink.classes()).toContain('bg-muted');
    },
  );

  it('renders the canonical top-level labels without chat or AI entries', async () => {
    const { wrapper } = await mountShell('/dashboard');
    const labels = wrapper
      .get('[data-testid="desktop-main-nav"]')
      .findAll('a[aria-label], button[aria-label]')
      .map((node) => node.attributes('aria-label'));
    expect(labels).toEqual(['动态', '时间线', '研究', '分析', '市场', '任务中心']);
    expect(wrapper.text()).not.toContain('问股');
    expect(wrapper.text()).not.toContain('AI');
    wrapper.unmount();
  });

  it('marks analysis as the only active primary destination', async () => {
    const { wrapper } = await mountShell('/analysis');
    expect(wrapper.get('[data-testid="desktop-main-nav"] a[aria-label="分析"]').attributes('aria-current')).toBe('page');
    expect(wrapper.get('button[aria-label="研究"]').attributes('aria-current')).toBeUndefined();
    expect(wrapper.get('button[aria-label="市场"]').attributes('aria-current')).toBeUndefined();
    wrapper.unmount();
  });

  it('selects theme preference from radio items and keeps system selected when OS is dark', async () => {
    useAuthStore().currentUser = {
      uid: 1,
      username: 'Alice',
      email: 'alice@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: { gender: 'female' },
    };
    systemPrefersDark.value = true;
    theme.value = 'system';
    localStorage.setItem('theme', 'system');
    const { wrapper } = await mountShell('/analysis');

    await openThemePreference(wrapper);

    const radios = [...document.body.querySelectorAll<HTMLElement>('[role="menuitemradio"]')];
    const byLabel = (label: string) => radios.find((item) => item.textContent?.includes(label));
    const systemItem = byLabel('跟随系统')!;
    const lightItem = byLabel('浅色')!;
    const darkItem = byLabel('深色')!;

    expect(systemItem.getAttribute('aria-checked')).toBe('true');
    expect(lightItem.getAttribute('aria-checked')).toBe('false');
    expect(darkItem.getAttribute('aria-checked')).toBe('false');

    darkItem.focus();
    darkItem.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await vi.waitFor(() => expect(localStorage.getItem('theme')).toBe('dark'));
    expect(theme.value).toBe('dark');

    if (!document.body.querySelector('[data-testid="theme-preference"]')) {
      await openThemePreference(wrapper);
    }
    await vi.waitFor(() => {
      expect(document.body.querySelector('[data-testid="theme-preference"]')).not.toBeNull();
    });
    const radiosAfterDark = [...document.body.querySelectorAll<HTMLElement>('[role="menuitemradio"]')];
    const darkItemAfter = radiosAfterDark.find((item) => item.textContent?.includes('深色'))!;
    const systemItemAfter = radiosAfterDark.find((item) => item.textContent?.includes('跟随系统'))!;
    expect(darkItemAfter.getAttribute('aria-checked')).toBe('true');
    expect(systemItemAfter.getAttribute('aria-checked')).toBe('false');

    const lightItemAfter = radiosAfterDark.find((item) => item.textContent?.includes('浅色'))!;
    lightItemAfter.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await vi.waitFor(() => expect(localStorage.getItem('theme')).toBe('light'));
    expect(theme.value).toBe('light');

    wrapper.unmount();
  });

  it('ignores null theme radio updates so the current preference is kept', async () => {
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

    await openThemePreference(wrapper);

    const radioGroup = wrapper.findComponent({ name: 'DropdownMenuRadioGroup' });
    expect(radioGroup.exists()).toBe(true);
    radioGroup.vm.$emit('update:modelValue', null);
    await wrapper.vm.$nextTick();

    expect(theme.value).toBe('light');
    expect(localStorage.getItem('theme')).toBe('light');
    wrapper.unmount();
  });

  it('keeps the desktop navigation visible and links the logo to the dashboard', async () => {
    const { wrapper } = await mountShell('/dashboard');
    expect(wrapper.get('[data-testid="desktop-main-nav"]').classes()).not.toContain('hidden');
    expect(wrapper.get('a[aria-label="回到动态"]').attributes('href')).toBe('/dashboard');
    expect(wrapper.get('a[aria-label="动态"]').attributes('aria-current')).toBe('page');
    wrapper.unmount();
  });
});
