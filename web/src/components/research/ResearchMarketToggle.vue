<script setup lang="ts">
import { Button } from '@/components/ui/button';

defineProps<{ modelValue: 'US' | 'CN' }>();
const emit = defineEmits<{ 'update:modelValue': [value: 'US' | 'CN'] }>();
const options = [{ value: 'US', label: '美股' }, { value: 'CN', label: 'A股' }] as const;
</script>

<template>
  <div
    class="flex h-10 shrink-0 items-center gap-1 rounded-lg bg-muted p-1"
    role="radiogroup"
    aria-label="市场"
  >
    <Button
      v-for="option in options"
      :key="option.value"
      size="sm"
      :variant="modelValue === option.value ? 'default' : 'ghost'"
      role="radio"
      :aria-checked="modelValue === option.value"
      @click="emit('update:modelValue', option.value)"
      @keydown.left.prevent="emit('update:modelValue', modelValue === 'US' ? 'CN' : 'US')"
      @keydown.right.prevent="emit('update:modelValue', modelValue === 'US' ? 'CN' : 'US')"
    >
      {{ option.label }}
    </Button>
  </div>
</template>
