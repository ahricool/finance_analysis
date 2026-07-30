<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/utils/cn';
import { Eye, EyeOff } from 'lucide-vue-next';
import { computed, ref, useAttrs, useId } from 'vue';

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{
  modelValue?: string | number | null;
  label?: string;
  hint?: string;
  error?: string;
  id?: string;
  name?: string;
  type?: string;
  class?: string;
  allowTogglePassword?: boolean;
  passwordVisible?: boolean;
  disabled?: boolean;
}>(), {
  type: 'text', class: '', modelValue: undefined, label: '', hint: '', error: '', id: undefined,
  name: undefined, allowTogglePassword: false, passwordVisible: undefined, disabled: false,
});
const emit = defineEmits<{
  'update:modelValue': [value: string];
  'update:passwordVisible': [value: boolean];
}>();
const attrs = useAttrs();
const generatedId = useId();
const inputId = computed(() => props.id ?? props.name ?? generatedId);
const internalPasswordVisible = ref(false);
const actualPasswordVisible = computed(() => props.passwordVisible ?? internalPasswordVisible.value);
const effectiveType = computed(() => props.type === 'password' && actualPasswordVisible.value ? 'text' : props.type);
const forwardedAttrs = computed(() => Object.fromEntries(Object.entries(attrs).filter(([key]) => key !== 'icon-type' && key !== 'iconType')));

function togglePasswordVisibility() {
  if (props.disabled) return;
  const next = !actualPasswordVisible.value;
  if (props.passwordVisible === undefined) internalPasswordVisible.value = next;
  emit('update:passwordVisible', next);
}
</script>

<template>
  <div :class="cn('grid min-w-0 gap-2', props.class)">
    <Label
      v-if="label"
      :for="inputId"
    >{{ label }}</Label>
    <div class="relative">
      <Input
        :id="inputId"
        v-bind="forwardedAttrs"
        :name="name"
        :type="effectiveType"
        :disabled="disabled"
        :model-value="modelValue ?? ''"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined"
        :class="allowTogglePassword && type === 'password' ? 'pr-11' : ''"
        @update:model-value="emit('update:modelValue', String($event))"
      />
      <Button
        v-if="allowTogglePassword && type === 'password'"
        variant="ghost"
        size="icon-sm"
        class="absolute right-1 top-1/2 -translate-y-1/2"
        :disabled="disabled"
        :aria-label="actualPasswordVisible ? '隐藏内容' : '显示内容'"
        @click="togglePasswordVisibility"
      >
        <EyeOff v-if="actualPasswordVisible" />
        <Eye v-else />
      </Button>
      <div
        v-if="$slots.trailing"
        class="absolute inset-y-0 right-2 flex items-center"
      >
        <slot name="trailing" />
      </div>
    </div>
    <p
      v-if="error"
      :id="`${inputId}-error`"
      class="text-xs text-destructive"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-else-if="hint"
      :id="`${inputId}-hint`"
      class="text-xs text-muted-foreground"
    >
      {{ hint }}
    </p>
  </div>
</template>
