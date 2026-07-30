import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import ModuleTabs from '../ModuleTabs.vue';

describe('ModuleTabs', () => {
  it('uses standard tabs with a horizontal scroll area and active route state', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/one', component: { template: '<div />' } },
        { path: '/two', component: { template: '<div />' } },
      ],
    });
    await router.push('/two');
    await router.isReady();

    const wrapper = mount(ModuleTabs, {
      props: {
        label: '模块导航',
        activeKey: 'two',
        items: [
          { key: 'one', label: '总览', to: '/one' },
          { key: 'two', label: '详情', to: '/two' },
        ],
      },
      global: { plugins: [router] },
    });

    expect(wrapper.get('nav').attributes('aria-label')).toBe('模块导航');
    expect(wrapper.get('[data-reka-scroll-area-viewport]').attributes()).toHaveProperty(
      'data-reka-scroll-area-viewport',
    );
    expect(wrapper.get('a[href="/two"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/one"]').attributes('data-state')).toBe('inactive');
  });
});
