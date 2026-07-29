import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import AppInput from '../AppInput.vue';

describe('AppInput password visibility', () => {
  it('toggles an uncontrolled password input and restores it after a second click', async () => {
    const wrapper = mount(AppInput, {
      props: { type: 'password', allowTogglePassword: true, label: '登录密码' },
    });
    const input = wrapper.get('input');
    const toggle = wrapper.get('button[aria-label="显示内容"]');

    expect(input.attributes('type')).toBe('password');
    await toggle.trigger('click');
    expect(input.attributes('type')).toBe('text');
    expect(wrapper.get('button').attributes('aria-label')).toBe('隐藏内容');

    await wrapper.get('button').trigger('click');
    expect(input.attributes('type')).toBe('password');
  });

  it('emits updates in controlled mode and follows the controlled value', async () => {
    const wrapper = mount(AppInput, {
      props: {
        type: 'password',
        allowTogglePassword: true,
        passwordVisible: false,
      },
    });

    await wrapper.get('button').trigger('click');
    expect(wrapper.emitted('update:passwordVisible')).toEqual([[true]]);
    expect(wrapper.get('input').attributes('type')).toBe('password');

    await wrapper.setProps({ passwordVisible: true });
    expect(wrapper.get('input').attributes('type')).toBe('text');
  });

  it('does not toggle while disabled', async () => {
    const wrapper = mount(AppInput, {
      props: {
        type: 'password',
        allowTogglePassword: true,
        disabled: true,
      },
    });

    const toggle = wrapper.get('button');
    expect(toggle.attributes()).toHaveProperty('disabled');
    await toggle.trigger('click');
    expect(wrapper.get('input').attributes('type')).toBe('password');
    expect(wrapper.emitted('update:passwordVisible')).toBeUndefined();
  });

  it('does not forward the removed icon-type attribute to the native input', () => {
    const wrapper = mount(AppInput, {
      attrs: { 'icon-type': 'password' },
      props: { type: 'password' },
    });

    expect(wrapper.get('input').attributes('icon-type')).toBeUndefined();
  });
});
