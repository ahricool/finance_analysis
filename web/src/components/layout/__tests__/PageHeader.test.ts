import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import PageHeader from '../PageHeader.vue';

describe('PageHeader', () => {
  it('keeps a nested research title at h2 and wraps actions below it', () => {
    const wrapper = mount(PageHeader, {
      props: { title: '行业强度', en: 'Industry Strength', variant: 'section' },
      slots: { actions: '<button>刷新</button><button>运行</button>' },
    });
    expect(wrapper.find('h1').exists()).toBe(false);
    expect(wrapper.get('h2').text()).toBe('行业强度');
    expect(wrapper.get('header').classes()).not.toContain('md:flex-row');
    expect(wrapper.get('.research-toolbar').findAll('button').map(button => button.text())).toEqual(['刷新', '运行']);
  });

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
