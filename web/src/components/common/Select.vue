<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, useId } from 'vue';

export interface SelectOption {
  value: string;
  label: string;
}

const props = withDefaults(
  defineProps<{
    id?: string;
    modelValue: string;
    options: SelectOption[];
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    class?: string;
  }>(),
  {
    placeholder: '请选择',
    disabled: false,
    class: '',
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();

const selectId = useId();
const resolvedId = computed(() => props.id ?? selectId);

const hasEmptyOption = computed(() => props.options.some((option) => option.value === ''));
</script>

<template>
  <div :class="cn('flex flex-col', props.class)">
    <label v-if="label" :for="resolvedId" class="mb-2 text-sm font-medium text-foreground">{{
      label
    }}</label>
    <div class="relative">
      <select
        :id="resolvedId"
        :value="modelValue"
        :disabled="disabled"
        :class="
          cn(
            'input-surface input-focus-glow h-11 w-full appearance-none rounded-xl border bg-transparent px-4 py-2.5 pr-10 text-sm text-foreground',
            'transition-all duration-200 focus:outline-none',
            disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
          )
        "
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="placeholder && !hasEmptyOption" value="" disabled>
          {{ placeholder }}
        </option>
        <option
          v-for="option in options"
          :key="option.value"
          :value="option.value"
          class="bg-elevated text-foreground"
        >
          {{ option.label }}
        </option>
      </select>

      <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
        <svg class="h-4 w-4 text-secondary-text" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  </div>
</template>
