<script setup lang="ts">
import { computed, useAttrs, useId } from 'vue';
import { Eye, EyeOff } from 'lucide-vue-next';
import AppButton from './AppButton.vue';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

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
}>(), { type: 'text', class: '', allowTogglePassword: false, passwordVisible: false });
const emit = defineEmits<{
  'update:modelValue': [value: string];
  'update:passwordVisible': [value: boolean];
}>();
const attrs = useAttrs();
const generatedId = useId();
const inputId = computed(() => props.id ?? props.name ?? generatedId);
const effectiveType = computed(() => props.type === 'password' && props.passwordVisible ? 'text' : props.type);
</script>

<template>
  <div :class="cn('grid min-w-0 gap-2', props.class)">
    <Label v-if="label" :for="inputId">{{ label }}</Label>
    <div class="relative">
      <Input
        :id="inputId"
        v-bind="attrs"
        :name="name"
        :type="effectiveType"
        :model-value="modelValue ?? ''"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined"
        :class="allowTogglePassword && type === 'password' ? 'pr-11' : ''"
        @update:model-value="emit('update:modelValue', String($event))"
      />
      <AppButton
        v-if="allowTogglePassword && type === 'password'"
        variant="ghost"
        size="icon-sm"
        class="absolute right-1 top-1/2 -translate-y-1/2"
        :aria-label="passwordVisible ? '隐藏内容' : '显示内容'"
        @click="emit('update:passwordVisible', !passwordVisible)"
      >
        <EyeOff v-if="passwordVisible" />
        <Eye v-else />
      </AppButton>
      <div v-if="$slots.trailing" class="absolute inset-y-0 right-2 flex items-center"><slot name="trailing" /></div>
    </div>
    <p v-if="error" :id="`${inputId}-error`" class="text-xs text-destructive" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="`${inputId}-hint`" class="text-xs text-muted-foreground">{{ hint }}</p>
  </div>
</template>
