import { parseDate } from '@internationalized/date';
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { Calendar } from '@/components/ui/calendar';
import AppDatePicker from '../AppDatePicker.vue';

describe('AppDatePicker available dates', () => {
  it('marks dates outside the snapshot list as unavailable and bounds the calendar', async () => {
    const wrapper = mount(AppDatePicker, {
      props: {
        modelValue: '2026-08-25',
        availableDates: ['2026-08-25', '2026-08-21'],
      },
      attachTo: document.body,
    });

    await wrapper.get('button').trigger('click');
    const calendar = wrapper.getComponent(Calendar);
    const isUnavailable = calendar.props('isDateUnavailable') as (date: { toString(): string }) => boolean;

    expect(isUnavailable(parseDate('2026-08-25'))).toBe(false);
    expect(isUnavailable(parseDate('2026-08-21'))).toBe(false);
    expect(isUnavailable(parseDate('2026-08-22'))).toBe(true);
    expect(calendar.props('minValue')?.toString()).toBe('2026-08-21');
    expect(calendar.props('maxValue')?.toString()).toBe('2026-08-25');
  });
});


it('does not emit a cleared date when clearable is false', async () => {
  const wrapper = mount(AppDatePicker, { props: { modelValue: '2026-09-09', clearable: false } });
  await wrapper.get('button').trigger('click');
  wrapper.getComponent(Calendar).vm.$emit('update:modelValue', undefined);
  expect(wrapper.emitted('update:modelValue')).toBeUndefined();
  expect(wrapper.text()).toContain('2026年9月9日');
  wrapper.unmount();
});
