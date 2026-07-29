<script setup lang="ts">
import { computed } from 'vue';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export type AppSelectOption = { value: string; label: string; disabled?: boolean };
const EMPTY_VALUE = '__app_select_empty__';
const props = withDefaults(defineProps<{
  modelValue?: string;
  options: AppSelectOption[];
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  class?: string;
}>(), { modelValue: '', label: '', placeholder: '请选择', disabled: false, class: '' });
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const selectValue = computed(() => props.modelValue === '' ? EMPTY_VALUE : props.modelValue);
function update(value: unknown) { emit('update:modelValue', String(value ?? '') === EMPTY_VALUE ? '' : String(value ?? '')); }
</script>

<template>
  <div :class="['grid min-w-0 gap-2', props.class]">
    <Label v-if="label">{{ label }}</Label>
    <Select :model-value="selectValue" :disabled="disabled" @update:model-value="update">
      <SelectTrigger class="h-10 w-full"><SelectValue :placeholder="placeholder" /></SelectTrigger>
      <SelectContent class="max-h-[min(20rem,60dvh)]">
        <SelectItem v-for="option in options" :key="option.value" :value="option.value === '' ? EMPTY_VALUE : option.value" :disabled="option.disabled">
          {{ option.label }}
        </SelectItem>
      </SelectContent>
    </Select>
  </div>
</template>
