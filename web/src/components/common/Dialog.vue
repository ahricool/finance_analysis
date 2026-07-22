<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, useId, watchEffect } from 'vue';

const props = withDefaults(
  defineProps<{
    isOpen: boolean;
    title: string;
    description?: string;
    eyebrow?: string;
    width?: string;
    zIndex?: number;
    contentClass?: string;
  }>(),
  {
    description: '',
    eyebrow: '',
    width: 'max-w-2xl',
    zIndex: 50,
    contentClass: '',
  },
);

const emit = defineEmits<{
  close: [];
}>();

let activeDialogCount = 0;
const uid = useId();
const titleId = `dialog-title-${uid}`;
const descriptionId = `dialog-description-${uid}`;
const panelClass = computed(() => cn(
  'pointer-events-auto relative flex max-h-[calc(100vh-2rem)] w-full flex-col rounded-2xl',
  'border border-border/70 bg-card shadow-soft-card-strong animate-in fade-in zoom-in duration-200',
  'sm:max-h-[calc(100vh-3rem)]',
  props.width,
));

function handleKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close');
}

watchEffect((onCleanup) => {
  if (!props.isOpen) return;

  document.addEventListener('keydown', handleKeyDown);
  activeDialogCount += 1;
  if (activeDialogCount === 1) document.body.style.overflow = 'hidden';

  onCleanup(() => {
    document.removeEventListener('keydown', handleKeyDown);
    activeDialogCount -= 1;
    if (activeDialogCount === 0) document.body.style.overflow = '';
  });
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 overflow-hidden"
      role="presentation"
      :style="{ zIndex }"
    >
      <div
        class="absolute inset-0 bg-background/80 backdrop-blur-sm transition-opacity duration-200"
        data-testid="dialog-backdrop"
        @click="emit('close')"
      />
      <div class="pointer-events-none absolute inset-0 flex w-full items-center justify-center p-4 sm:p-6">
        <div
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-describedby="description ? descriptionId : undefined"
          :class="panelClass"
          data-testid="dialog-panel"
        >
          <header class="flex shrink-0 items-start justify-between gap-4 border-b border-border/60 px-4 py-4 sm:px-6">
            <div class="min-w-0">
              <span v-if="eyebrow" class="label-uppercase">{{ eyebrow }}</span>
              <h2 :id="titleId" :class="cn('text-lg font-semibold text-foreground', eyebrow && 'mt-1')">
                {{ title }}
              </h2>
              <p v-if="description" :id="descriptionId" class="mt-1 text-sm leading-5 text-secondary-text">
                {{ description }}
              </p>
            </div>
            <button
              type="button"
              class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-card/80 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
              aria-label="关闭弹窗"
              @click="emit('close')"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </header>
          <div :class="cn('min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-6', contentClass)">
            <slot />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
