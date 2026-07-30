import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import PageHeader from '../PageHeader.vue';

describe('PageHeader', () => {
  it('composes optional breadcrumb, description, and responsive actions', () => {
    const wrapper = mount(PageHeader, {
      props: {
        title: '任务中心',
        description: '查看计划任务与执行记录。',
        section: '运维',
      },
      slots: { actions: '<button type="button">新建任务</button>' },
    });

    expect(wrapper.get('h1').text()).toBe('任务中心');
    expect(wrapper.get('[aria-label="breadcrumb"]').text()).toContain('运维');
    expect(wrapper.get('[aria-label="breadcrumb"]').text()).toContain('任务中心');
    expect(wrapper.text()).toContain('查看计划任务与执行记录。');
    expect(wrapper.get('button').text()).toBe('新建任务');
    expect(wrapper.get('header').classes()).toEqual(
      expect.arrayContaining(['flex-col', 'md:flex-row']),
    );
  });
});
