import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import SectionNavItems from '../SectionNavItems.vue';

const Icon = { template: '<svg aria-hidden="true" />' };

describe('SectionNavItems', () => {
  it('uses one size and color system for links and button tabs', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    });
    await router.push('/');
    await router.isReady();

    const wrapper = mount(SectionNavItems, {
      props: {
        activeKey: 'overview',
        items: [
          { key: 'overview', label: '总览', icon: Icon, to: '/' },
          { key: 'settings', label: '设置', icon: Icon },
        ],
      },
      global: { plugins: [router] },
    });

    const link = wrapper.get('a');
    const button = wrapper.get('button');
    for (const item of [link, button]) {
      expect(item.classes()).toContain('h-11');
      expect(item.classes()).toContain('text-sm');
      expect(item.classes()).toContain('font-medium');
      expect(item.get('svg').classes()).toEqual(expect.arrayContaining(['h-4', 'w-4']));
    }
    expect(link.classes()).toContain('text-primary');
    expect(button.classes()).toContain('text-secondary-text');

    await button.trigger('click');
    expect(wrapper.emitted('select')).toEqual([['settings']]);
  });
});
