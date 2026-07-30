import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SettingsSectionCard from '../SettingsSectionCard.vue';

describe('SettingsSectionCard', () => {
  it('matches task-center card and heading sizing', () => {
    const wrapper = mount(SettingsSectionCard, {
      props: { title: '我的信息' },
      slots: { default: '<p>内容</p>' },
    });

    expect(wrapper.attributes('data-slot')).toBe('card');
    const title = wrapper.get('[data-slot="card-title"]');
    expect(title.classes()).toEqual(expect.arrayContaining(['font-medium']));
    expect(title.classes()).not.toContain('uppercase');
  });
});
