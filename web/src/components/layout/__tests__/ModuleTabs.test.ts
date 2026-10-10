import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import ModuleTabs from '../ModuleTabs.vue';

describe('ModuleTabs', () => {
  it('exposes route links with the current page', async () => {
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
    expect(wrapper.get('a[href="/two"]').attributes('aria-current')).toBe('page');
    expect(wrapper.get('a[href="/one"]').attributes('aria-current')).toBeUndefined();
    await wrapper.get('a[href="/one"]').trigger('click');
    expect(wrapper.emitted('navigate')).toHaveLength(1);
    expect(wrapper.get('a[href="/two"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/one"]').attributes('data-state')).toBe('inactive');
  });
});
