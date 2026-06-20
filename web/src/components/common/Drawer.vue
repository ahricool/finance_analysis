<script setup lang="ts">
import { computed, watchEffect, useId } from 'vue';
import { cn } from '@/utils/cn';

const props = withDefaults(
  defineProps<{
    isOpen: boolean;
    title?: string;
    width?: string;
    zIndex?: number;
    side?: 'left' | 'right';
    variant?: 'drawer' | 'modal';
    backdropClassName?: string;
  }>(),
  {
    width: 'max-w-2xl',
    zIndex: 50,
    side: 'right',
    variant: 'drawer',
  },
);

const emit = defineEmits<{
  close: [];
}>();

let activeDrawerCount = 0;

const uid = useId();
const titleId = `drawer-title-${props.side}-${uid}`;
const panelWrapperClass = computed(() =>
  cn(
    'pointer-events-none absolute flex w-full',
    props.variant === 'modal'
      ? 'inset-0 items-center justify-center p-4 sm:p-6'
      : ['inset-y-0', props.side === 'left' ? 'left-0 justify-start' : 'right-0 justify-end', props.width],
  ),
);
const panelClass = computed(() =>
  cn(
    'pointer-events-auto relative flex w-full flex-col bg-card',
    props.variant === 'modal'
      ? [
          props.width,
          'max-h-[calc(100vh-2rem)] rounded-2xl border border-border/70 shadow-soft-card-strong animate-in fade-in zoom-in duration-200 sm:max-h-[calc(100vh-3rem)]',
        ]
      : [
          props.side === 'left' ? 'border-r' : 'border-l',
          props.side === 'right' ? 'border-border/80' : 'border-border/70 shadow-2xl',
          props.side === 'left' ? 'animate-slide-in-left' : 'animate-slide-in-right',
        ],
  ),
);
const closeLabel = computed(() => (props.variant === 'modal' ? '关闭弹窗' : '关闭抽屉'));

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close');
  }
}

watchEffect((onCleanup) => {
  if (!props.isOpen) return;

  document.addEventListener('keydown', handleKeyDown);
  activeDrawerCount++;
  if (activeDrawerCount === 1) {
    document.body.style.overflow = 'hidden';
  }

  onCleanup(() => {
    document.removeEventListener('keydown', handleKeyDown);
    activeDrawerCount--;
    if (activeDrawerCount === 0) {
      document.body.style.overflow = '';
    }
  });
});

</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 overflow-hidden"
      role="presentation"
      :style="{ zIndex: zIndex }"
    >
      <div
        :class="cn('absolute inset-0 bg-background/80 backdrop-blur-sm transition-opacity duration-300', backdropClassName)"
        @click="emit('close')"
      />

      <div :class="panelWrapperClass">
        <div
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :class="panelClass"
        >
          <div class="flex items-center justify-between border-b border-border/60 px-6 py-4">
            <div v-if="title">
              <span class="label-uppercase">DETAIL VIEW</span>
              <h2 :id="titleId" class="mt-1 text-lg font-semibold text-foreground">
                {{ title }}
              </h2>
            </div>
            <div v-else />
            <button
              type="button"
              class="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/80 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
              :aria-label="closeLabel"
              @click="emit('close')"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="flex-1 overflow-y-auto p-6">
            <slot />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
