<script setup lang="ts">
import { computed } from 'vue';
import type { ParsedApiError } from '@/api/error';

const props = withDefaults(
  defineProps<{
    error: ParsedApiError;
    class?: string;
    actionLabel?: string;
    dismissLabel?: string;
  }>(),
  {
    class: '',
    dismissLabel: '关闭',
  },
);

const emit = defineEmits<{
  dismiss: [];
  action: [];
}>();

const showDetails = computed(
  () =>
    props.error.rawMessage.trim() !== '' &&
    props.error.rawMessage.trim() !== props.error.message.trim(),
);
</script>

<template>
  <div
    :class="`rounded-xl border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-4 py-3 text-[hsl(var(--color-danger-alert-text))] ${props.class}`"
    role="alert"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-sm font-semibold">{{ error.title }}</p>
        <p class="mt-1 text-xs opacity-90">{{ error.message }}</p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-md border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-2 py-1 text-[11px] text-[hsl(var(--color-danger-alert-text))] transition hover:bg-[hsl(var(--color-danger-alert-bg)/0.15)]"
        @click="emit('dismiss')"
      >
        {{ dismissLabel }}
      </button>
    </div>
    <details v-if="showDetails" class="mt-3 rounded-lg border border-subtle bg-surface-2 px-3 py-2">
      <summary class="cursor-pointer text-xs text-[hsl(var(--color-danger-alert-text))] opacity-90">
        查看详情
      </summary>
      <pre
        class="mt-2 whitespace-pre-wrap break-words text-[11px] leading-5 text-[hsl(var(--color-danger-alert-text))] opacity-85"
      >{{ error.rawMessage }}</pre>
    </details>
    <button
      v-if="actionLabel"
      type="button"
      class="mt-3 inline-flex items-center justify-center rounded-md border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-3 py-1.5 text-xs font-medium text-[hsl(var(--color-danger-alert-text))] transition hover:bg-[hsl(var(--color-danger-alert-bg)/0.15)]"
      @click="emit('action')"
    >
      {{ actionLabel }}
    </button>
  </div>
</template>
