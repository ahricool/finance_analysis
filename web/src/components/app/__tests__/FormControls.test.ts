import { flushPromises, mount } from '@vue/test-utils';
import { Select } from '@/components/ui/select';
import { Popover } from '@/components/ui/popover';
import { describe, expect, it } from 'vitest';
import AppCombobox from '../AppCombobox.vue';
import AppDatePicker from '../AppDatePicker.vue';
import AppDateTimePicker from '../AppDateTimePicker.vue';
import FieldSelect from '../../forms/FieldSelect.vue';
import AppTimePicker from '../AppTimePicker.vue';

function expectAccessibleControl(
  wrapper: ReturnType<typeof mount>,
  selector: string,
  error: string,
) {
  const label = wrapper.get('label');
  const control = wrapper.get(selector);
  const errorElement = wrapper.get('[role="alert"]');

  expect(label.attributes('for')).toBe(control.attributes('id'));
  expect(control.attributes('aria-invalid')).toBe('true');
  expect(control.attributes('aria-describedby')).toBe(errorElement.attributes('id'));
  expect(errorElement.text()).toBe(error);
}

describe('application form control accessibility', () => {
  it('associates Select labels and errors with the combobox trigger', () => {
    const wrapper = mount(FieldSelect, {
      props: {
        label: '市场',
        error: '请选择市场',
        options: [{ value: 'CN', label: 'A 股' }],
      },
    });
    expectAccessibleControl(wrapper, '[role="combobox"]', '请选择市场');
  });

  it('associates Combobox labels and errors with its trigger', () => {
    const wrapper = mount(AppCombobox, {
      props: {
        label: '标的',
        error: '请选择标的',
        options: [{ value: 'AAPL.US', label: 'Apple' }],
      },
    });
    expectAccessibleControl(wrapper, '[role="combobox"]', '请选择标的');
  });

  it.each([
    [AppDatePicker, '开始日期', '请选择日期'],
    [AppTimePicker, '记录时间', '请选择时间'],
    [AppDateTimePicker, '执行时间', '请选择日期和时间'],
  ])('associates %s labels and errors with the button trigger', (component, label, error) => {
    const wrapper = mount(component, { props: { label, error } });
    expectAccessibleControl(wrapper, 'button', error);
  });
});

it('forwards trigger attributes and keeps empty and zero select values distinct', async () => {
  const wrapper = mount(FieldSelect, {
    props: { modelValue: '', options: [{ value: '', label: '全部' }, { value: '0', label: '版本 0' }] },
    attrs: { 'aria-label': '预测版本', 'data-testid': 'version-choice' },
  });
  await flushPromises();
  const trigger = wrapper.get('[role="combobox"]');
  expect(trigger.attributes('aria-label')).toBe('预测版本');
  expect(trigger.attributes('data-testid')).toBe('version-choice');
  expect(trigger.text()).toContain('全部');
  wrapper.getComponent(Select).vm.$emit('update:modelValue', '0');
  await flushPromises();
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['0']);
  expect(wrapper.emitted('change')?.at(-1)).toEqual(['0']);
  await wrapper.setProps({ modelValue: '0' });
  expect(trigger.text()).toContain('版本 0');
  wrapper.getComponent(Select).vm.$emit('update:modelValue', '');
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['']);
  wrapper.unmount();
});

it('shows the placeholder when no empty option exists and keeps combobox popovers nonmodal', () => {
  const select = mount(FieldSelect, { props: { options: [{ value: 'a', label: 'Alpha' }], placeholder: '选择版本' } });
  expect(select.get('[role="combobox"]').text()).toContain('选择版本');
  const combo = mount(AppCombobox, { props: { options: [{ value: 'a', label: 'Alpha' }] } });
  expect(combo.getComponent(Popover).props('modal')).toBe(false);
  select.unmount(); combo.unmount();
});
