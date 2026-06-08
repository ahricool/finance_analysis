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
    expect(popup.text()).toContain('Alice');
    expect(popup.text()).toContain('邮箱：');
    expect(popup.text()).toContain('alice@example.com');
    expect(popup.text()).toContain('角色：');
    expect(popup.text()).toContain('admin');
    expect(popup.get('button').text()).toBe('退出');
  });
});
