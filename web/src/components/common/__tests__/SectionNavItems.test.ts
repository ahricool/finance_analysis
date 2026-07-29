import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import SectionNavItems from '../SectionNavItems.vue';

const Icon = { template: '<svg aria-hidden="true" />' };

describe('SectionNavItems', () => {
  it('keeps link navigation and local button selection visually aligned', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/details', component: { template: '<div />' } },
      ],
    });
    await router.push('/');
    await router.isReady();

    const wrapper = mount(SectionNavItems, {
      props: {
        activeKey: 'overview',
        items: [
          { key: 'overview', label: '总览', icon: Icon, to: '/details' },
          { key: 'settings', label: '设置', icon: Icon },
        ],
      },
      global: { plugins: [router] },
    });

    const link = wrapper.get('a');
    const button = wrapper.get('button');
    expect(link.attributes('href')).toBe('/details');
    expect(button.attributes('type')).toBe('button');
    for (const item of [link, button]) {
      expect(item.classes()).toEqual(
        expect.arrayContaining([
          'h-11',
          'font-sans',
          'text-sm',
          'font-medium',
          'leading-5',
          'tracking-normal',
        ]),
      );
      expect(item.get('svg').classes()).toEqual(expect.arrayContaining(['h-4', 'w-4']));
    }
    expect(link.classes()).toContain('text-primary');
    expect(button.classes()).toContain('text-secondary-text');
    expect(button.classes()).toEqual(expect.arrayContaining(['appearance-none', 'border-0']));

    await button.trigger('click');
    expect(wrapper.emitted('select')).toEqual([['settings']]);

    await link.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/details');
  });
});
