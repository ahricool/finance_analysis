import { mount } from '@vue/test-utils';
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
