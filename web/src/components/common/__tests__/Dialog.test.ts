import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import Dialog from '../Dialog.vue';

describe('Dialog', () => {
  it('renders a centered modal and closes from the backdrop, close button, and Escape', async () => {
    const wrapper = mount(Dialog, {
      props: { isOpen: true, title: '测试弹窗' },
      slots: { default: '<p>弹窗内容</p>' },
      global: { stubs: { Teleport: true } },
    });

    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true');
    expect(wrapper.get('[data-testid="dialog-panel"]').classes()).toContain('rounded-2xl');

    await wrapper.get('[data-testid="dialog-backdrop"]').trigger('click');
    await wrapper.get('button[aria-label="关闭弹窗"]').trigger('click');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    expect(wrapper.emitted('close')).toHaveLength(3);
  });
});
