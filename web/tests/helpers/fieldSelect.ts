import { nextTick } from 'vue';
import type { VueWrapper } from '@vue/test-utils';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Select } from '@/components/ui/select';

/** Page tests drive the themed select's public event; browser tests cover keyboard/portal behavior. */
export function fieldSelect(wrapper: VueWrapper, trigger: string) {
  const field = wrapper.findAllComponents(FieldSelect).find(component => component.find(trigger).exists());
  if (!field) throw new Error(`Missing themed select: ${trigger}`);
  return field;
}

export async function setFieldSelect(wrapper: VueWrapper, trigger: string, value: string | number) {
  fieldSelect(wrapper, trigger).getComponent(Select).vm.$emit('update:modelValue', String(value));
  await nextTick();
}
