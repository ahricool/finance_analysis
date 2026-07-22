import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SettingsSectionCard from '../SettingsSectionCard.vue';

describe('SettingsSectionCard', () => {
  it('matches task-center card and heading sizing', () => {
    const wrapper = mount(SettingsSectionCard, {
      props: { title: '我的信息' },
      slots: { default: '<p>内容</p>' },
    });

    expect(wrapper.classes()).toEqual(expect.arrayContaining([
      'rounded-2xl',
      'border-border/70',
      'bg-card/94',
      'p-4',
      'shadow-soft-card',
    ]));
    expect(wrapper.get('h2').classes()).toEqual(expect.arrayContaining([
      'text-base',
      'font-semibold',
      'text-foreground',
    ]));
    expect(wrapper.get('h2').classes()).not.toContain('uppercase');
  });
});
