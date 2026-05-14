<script setup lang="ts">
import Button from '@/components/common/Button.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import { cn } from '@/utils/cn';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    title: string;
    message: string;
    variant?: 'error' | 'success' | 'warning';
    presentation?: 'inline' | 'toast';
    actionLabel?: string;
    class?: string;
  }>(),
  {
    variant: 'error',
    presentation: 'inline',
    class: '',
  },
);

const emit = defineEmits<{
  action: [];
}>();

const variantMap: Record<NonNullable<typeof props.variant>, 'danger' | 'success' | 'warning'> = {
  error: 'danger',
  success: 'success',
  warning: 'warning',
};

const toastHighlightStyle = [
  'relative overflow-hidden bg-card/95 text-foreground shadow-soft-card-strong backdrop-blur-sm',
  'before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-1.5',
  'before:bg-gradient-to-r before:from-cyan/80 before:via-primary/70 before:to-purple/70',
].join(' ');

const toastVariantStyles: Record<NonNullable<typeof props.variant>, string> = {
  error: toastHighlightStyle,
  success: toastHighlightStyle,
  warning: toastHighlightStyle,
};

const presentationClassName = computed(() =>
  props.presentation === 'toast' ? toastVariantStyles[props.variant] : '',
);
</script>

<template>
  <InlineAlert
    :title="title"
    :variant="variantMap[variant]"
    :class="cn(presentationClassName, props.class)"
  >
    {{ message }}
    <template v-if="actionLabel" #action>
      <Button
        type="button"
        variant="settings-secondary"
        size="xsm"
        @click="emit('action')"
      >
        {{ actionLabel }}
      </Button>
    </template>
  </InlineAlert>
</template>
