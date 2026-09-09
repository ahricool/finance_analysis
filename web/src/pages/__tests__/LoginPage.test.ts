import { mount, flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';
import LoginPage from '../LoginPage.vue';
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({
  lookupEmail: vi.fn().mockResolvedValue({ success: true, needsPasswordSetup: false }),
  login: vi.fn().mockResolvedValue({ success: true }), setupPassword: vi.fn(),
}) }));

describe('login destination', () => {
  it.each([
    ['/login', '/dashboard'], ['/login?redirect=/analysis', '/analysis'],
    ['/login?redirect=//outside.example', '/dashboard'],
  ])('routes %s to %s', async (entry, expected) => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] });
    await router.push(entry);
    const wrapper = mount(LoginPage, { global: { plugins: [router] } });
    await wrapper.get('[data-testid="login-email"]').setValue('reviewer@example.com');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    await wrapper.get('[data-testid="login-password"]').setValue('test-password');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe(expected);
    wrapper.unmount();
  });
});
