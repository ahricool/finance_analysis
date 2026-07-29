import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authApi, type UserProfileResponse } from '@/api/auth';
import ProfilePage from '../ProfilePage.vue';

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>();
  return {
    ...actual,
    authApi: {
      ...actual.authApi,
      getProfile: vi.fn(),
    },
  };
});

const profile: UserProfileResponse = {
  uid: 7,
  username: 'Alice',
  email: 'alice@example.com',
  avatarUrl: null,
  role: 'user',
  extra: {
    gender: 'female',
    notification: {
      ntfy: [{ url: 'https://ntfy.sh/alice' }],
      telegram: [{ bot_token: 'token', chat_id: 'chat' }],
    },
  },
};

async function mountProfile(path: string) {
  const pinia = createPinia();
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/profile', redirect: '/profile/info' },
      { path: '/profile/info', name: 'profile-info', component: ProfilePage },
      { path: '/profile/password', name: 'profile-password', component: ProfilePage },
      { path: '/profile/notification', name: 'profile-notification', component: ProfilePage },
    ],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(ProfilePage, {
    global: {
      plugins: [pinia, router],
    },
  });
  await flushPromises();
  return { router, wrapper };
}

describe('ProfilePage route navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(authApi.getProfile).mockResolvedValue(profile);
  });

  it.each([
    ['/profile/info', '/profile/info', '我的信息'],
    ['/profile/password', '/profile/password', '修改密码'],
    ['/profile/notification', '/profile/notification', '消息通知'],
  ])('activates the matching tab for %s', async (path, activeHref, sectionTitle) => {
    const { wrapper } = await mountProfile(path);
    const links = wrapper.findAll('aside a');

    expect(links).toHaveLength(3);
    expect(links.map((link) => link.attributes('href'))).toEqual([
      '/profile/info',
      '/profile/password',
      '/profile/notification',
    ]);
    expect(wrapper.find('aside button').exists()).toBe(false);
    expect(wrapper.get(`aside a[href="${activeHref}"]`).classes()).toContain('text-primary');
    expect(wrapper.get('section h2').text()).toBe(sectionTitle);
    expect(authApi.getProfile).toHaveBeenCalledTimes(1);

    wrapper.unmount();
  });

  it('switches tabs through the router without reloading profile data', async () => {
    const { router, wrapper } = await mountProfile('/profile/info');

    await wrapper.get('aside a[href="/profile/password"]').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/profile/password');
    expect(wrapper.get('aside a[href="/profile/password"]').classes()).toContain('text-primary');

    await wrapper.get('aside a[href="/profile/notification"]').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/profile/notification');
    expect(wrapper.get('aside a[href="/profile/notification"]').classes()).toContain('text-primary');

    router.back();
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/profile/password');
    expect(wrapper.get('aside a[href="/profile/password"]').classes()).toContain('text-primary');

    router.forward();
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/profile/notification');
    expect(authApi.getProfile).toHaveBeenCalledTimes(1);

    wrapper.unmount();
  });
});
