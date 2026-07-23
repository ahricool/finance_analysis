import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SectionNavPanel from '../SectionNavPanel.vue';
import SectionPageHeader from '../SectionPageHeader.vue';

const Icon = { template: '<svg aria-hidden="true" />' };

describe('section layout primitives', () => {
  it('keeps page heading typography consistent', () => {
    const wrapper = mount(SectionPageHeader, {
      props: {
        title: '个人中心',
        description: '管理账号资料。',
      },
    });

    expect(wrapper.get('header').classes()).toContain('font-sans');
    expect(wrapper.get('h1').classes()).toEqual(
      expect.arrayContaining(['text-xl', 'font-semibold', 'text-foreground']),
    );
    expect(wrapper.get('p').classes()).toEqual(
      expect.arrayContaining(['text-sm', 'text-muted-text']),
    );
  });

  it('uses one panel surface and typography for every desktop section nav', () => {
    const wrapper = mount(SectionNavPanel, {
      props: {
        activeKey: 'info',
        items: [{ key: 'info', label: '我的信息', icon: Icon }],
      },
    });

    expect(wrapper.get('aside').classes()).toEqual(
      expect.arrayContaining([
        'rounded-2xl',
        'border-border/70',
        'bg-card/94',
        'p-2',
        'font-sans',
        'shadow-soft-card',
      ]),
    );
    expect(wrapper.get('button').classes()).toEqual(
      expect.arrayContaining(['h-11', 'text-sm', 'font-medium', 'text-primary']),
    );
  });
});
