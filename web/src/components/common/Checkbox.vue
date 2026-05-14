<script setup lang="ts">
import { cn } from '@/utils/cn';
import { useId, useAttrs } from 'vue';

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    label?: string;
    id?: string;
    containerClass?: string;
    class?: string;
  }>(),
  {
    containerClass: '',
    class: '',
  },
);

const attrs = useAttrs();
const generatedId = useId();
const checkboxId = props.id ?? generatedId;
</script>

<template>
  <div :class="cn('flex items-center gap-3', containerClass)">
    <input
      :id="checkboxId"
      type="checkbox"
      :class="
        cn(
          'h-4 w-4 cursor-pointer rounded border border-border/70 bg-base text-cyan transition-all',
          'focus:ring-2 focus:ring-cyan/20 focus:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          props.class,
        )
      "
      v-bind="attrs"
    />
    <label
      v-if="label"
      :for="checkboxId"
      class="cursor-pointer select-none text-sm font-medium text-foreground"
    >
      {{ label }}
    </label>
  </div>
</template>
