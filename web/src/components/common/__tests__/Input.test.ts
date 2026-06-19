import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import Input from '../Input.vue';

describe('Input password visibility toggle', () => {
  it('switches password fields between hidden and visible text', async () => {
    const wrapper = mount(Input, {
      props: {
        type: 'password',
        allowTogglePassword: true,
        value: 'secret',
      },
    });

    expect(wrapper.get('input').attributes('type')).toBe('password');

    await wrapper.get('button[aria-label="显示内容"]').trigger('click');
    expect(wrapper.get('input').attributes('type')).toBe('text');

    await wrapper.get('button[aria-label="隐藏内容"]').trigger('click');
    expect(wrapper.get('input').attributes('type')).toBe('password');
  });

  it('applies sizing classes to the field container so the toggle aligns with the input edge', () => {
    const wrapper = mount(Input, {
      props: {
        type: 'password',
        allowTogglePassword: true,
        class: 'max-w-sm',
      },
    });

    expect(wrapper.classes()).toContain('max-w-sm');
    expect(wrapper.get('input').classes()).not.toContain('max-w-sm');
  });
});
