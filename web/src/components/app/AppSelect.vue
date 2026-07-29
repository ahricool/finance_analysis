<script setup lang="ts">
import { computed, useId } from 'vue';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export type AppSelectOption = { value: string; label: string; disabled?: boolean };
const EMPTY_VALUE = '__app_select_empty__';
const props = withDefaults(
  defineProps<{
    modelValue?: string;
    options: AppSelectOption[];
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    error?: string;
    hint?: string;
    id?: string;
    class?: string;
  }>(),
  {
    modelValue: '',
    label: '',
    placeholder: '请选择',
    disabled: false,
    error: '',
    hint: '',
    id: undefined,
    class: '',
  },
);
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const generatedId = useId();
const triggerId = computed(() => props.id ?? generatedId);
const descriptionId = computed(() =>
  props.error ? `${triggerId.value}-error` : props.hint ? `${triggerId.value}-hint` : undefined,
);
const selectValue = computed(() => (props.modelValue === '' ? EMPTY_VALUE : props.modelValue));
function update(value: unknown) {
  emit('update:modelValue', String(value ?? '') === EMPTY_VALUE ? '' : String(value ?? ''));
}
</script>

<template>
  <div :class="['grid min-w-0 gap-2', props.class]">
    <Label
      v-if="label"
      :for="triggerId"
    >{{ label }}</Label>
    <Select
      :model-value="selectValue"
      :disabled="disabled"
      @update:model-value="update"
    >
      <SelectTrigger
        :id="triggerId"
        class="h-10 w-full"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="descriptionId"
      >
        <SelectValue :placeholder="placeholder" />
      </SelectTrigger>
      <SelectContent class="max-h-[min(20rem,60dvh)]">
        <SelectItem
          v-for="option in options"
          :key="option.value"
          :value="option.value === '' ? EMPTY_VALUE : option.value"
          :disabled="option.disabled"
        >
          {{ option.label }}
        </SelectItem>
      </SelectContent>
    </Select>
    <p
      v-if="error"
      :id="`${triggerId}-error`"
      class="text-xs text-destructive"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-else-if="hint"
      :id="`${triggerId}-hint`"
      class="text-xs text-muted-foreground"
    >
      {{ hint }}
    </p>
  </div>
</template>
