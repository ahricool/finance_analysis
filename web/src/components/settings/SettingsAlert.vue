<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
    actionLabel: '',
    class: '',
  },
);

const emit = defineEmits<{
  action: [];
}>();

const toastHighlightStyle = [
  'relative overflow-hidden bg-card/95 text-foreground shadow-xl backdrop-blur-sm',
  'before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-1.5',
  'before:bg-gradient-to-r before:from-primary/80 before:via-primary/60 before:to-primary/30',
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
  <Alert
    :variant="variant === 'error' ? 'destructive' : 'default'"
    :class="cn(variant === 'success' && 'border-success/25 text-success', variant === 'warning' && 'border-warning/25 text-warning', presentationClassName, props.class)"
  >
    <AlertTitle>{{ title }}</AlertTitle>
    <AlertDescription :class="variant !== 'error' && 'text-current/80'">
      {{ message }}
    </AlertDescription>
    <div
      v-if="actionLabel"
      class="mt-3"
    >
      <Button
        type="button"
        variant="outline"
        size="xs"
        @click="emit('action')"
      >
        {{ actionLabel }}
      </Button>
    </div>
  </Alert>
</template>
