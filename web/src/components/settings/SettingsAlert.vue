<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { cn } from '@/utils/cn';

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

</script>

<template>
  <Alert
    :variant="variant === 'error' ? 'destructive' : 'default'"
    :class="cn(variant === 'success' && 'border-success/25 text-success', variant === 'warning' && 'border-warning/25 text-warning', props.presentation === 'toast' && 'bg-popover text-popover-foreground', props.class)"
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
