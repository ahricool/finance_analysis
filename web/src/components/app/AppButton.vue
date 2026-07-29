<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { LoaderCircle } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';

withDefaults(
  defineProps<{
    variant?: 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive' | 'link';
    size?: 'default' | 'xs' | 'sm' | 'lg' | 'icon' | 'icon-xs' | 'icon-sm' | 'icon-lg';
    loading?: boolean;
    loadingText?: string;
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    class?: HTMLAttributes['class'];
  }>(),
  {
    variant: 'default',
    size: 'default',
    loading: false,
    loadingText: '处理中…',
    type: 'button',
    disabled: false,
    class: '',
  },
);
</script>

<template>
  <Button
    :variant="variant"
    :size="size"
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    :class="$props.class"
  >
    <LoaderCircle
      v-if="loading"
      class="size-4 animate-spin"
    />
    <span v-if="loading">{{ loadingText }}</span>
    <slot v-else />
  </Button>
</template>
